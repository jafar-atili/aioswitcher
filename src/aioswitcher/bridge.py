# Copyright Tomer Figenblat.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Switcher integration, UDP Bridge module."""

from asyncio import BaseTransport, DatagramProtocol, get_running_loop
from binascii import hexlify
from dataclasses import dataclass
from functools import partial
from logging import getLogger
from socket import AF_INET, inet_ntoa
from struct import pack
from types import TracebackType
from typing import Any, Callable, Dict, Optional, Tuple, Type, final
from warnings import warn

from .device import (
    DeviceCategory,
    DeviceState,
    DeviceType,
    ShutterDirection,
    SwitcherBase,
    SwitcherPowerPlug,
    SwitcherShutter,
    SwitcherThermostat,
    SwitcherWaterHeater,
    ThermostatFanLevel,
    ThermostatMode,
    ThermostatSwing,
)
from .device.tools import seconds_to_iso_time, watts_to_amps

__all__ = ["SwitcherBridge"]
logger = getLogger(__name__)


# Protocol type 1 devices: V2, Touch, V4, Mini, Power Plug
SWITCHER_UDP_PORT_TYPE1 = 20002
# Protocol type 2 devices: Breeze, Runner, Runner Mini
SWITCHER_UDP_PORT_TYPE2 = 20003

SWITCHER_DEVICE_TO_UDP_PORT = {
    DeviceCategory.WATER_HEATER: SWITCHER_UDP_PORT_TYPE1,
    DeviceCategory.POWER_PLUG: SWITCHER_UDP_PORT_TYPE1,
    DeviceCategory.THERMOSTAT: SWITCHER_UDP_PORT_TYPE2,
    DeviceCategory.SHUTTER: SWITCHER_UDP_PORT_TYPE2,
}


def _parse_device_from_datagram(
    device_callback: Callable[[SwitcherBase], Any], datagram: bytes
) -> None:
    """Use as callback function to be called for every broadcast message.

    Will create devices and send to the on_device callback.

    Args:
        device_callback: callable for sending SwitcherBase devices parsed from message.
        broadcast_message: the bytes message to parse.

    """
    parser = DatagramParser(datagram)
    if not parser.is_switcher_originator():
        logger.debug("received datagram from an unknown source")
    else:
        device_type: DeviceType = parser.get_device_type()
        if device_type == DeviceType.BREEZE:
            device_state = parser.get_thermostat_state()
        else:
            device_state = parser.get_device_state()
        if device_state == DeviceState.ON:
            power_consumption = parser.get_power_consumption()
            electric_current = watts_to_amps(power_consumption)
        else:
            power_consumption = 0
            electric_current = 0.0

        if device_type and device_type.category == DeviceCategory.WATER_HEATER:
            logger.debug("discovered a water heater switcher device")
            device_callback(
                SwitcherWaterHeater(
                    device_type,
                    device_state,
                    parser.get_device_id(),
                    parser.get_ip_type1(),
                    parser.get_mac(),
                    parser.get_name(),
                    power_consumption,
                    electric_current,
                    (
                        parser.get_remaining()
                        if device_state == DeviceState.ON
                        else "00:00:00"
                    ),
                    parser.get_auto_shutdown(),
                )
            )

        elif device_type and device_type.category == DeviceCategory.POWER_PLUG:
            logger.debug("discovered a power plug switcher device")
            device_callback(
                SwitcherPowerPlug(
                    device_type,
                    device_state,
                    parser.get_device_id(),
                    parser.get_ip_type1(),
                    parser.get_mac(),
                    parser.get_name(),
                    power_consumption,
                    electric_current,
                )
            )

        elif device_type and device_type.category == DeviceCategory.SHUTTER:
            logger.debug("discovered a Runner switch switcher device")
            device_callback(
                SwitcherShutter(
                    device_type,
                    DeviceState.ON,
                    parser.get_device_id(),
                    parser.get_ip_type2(),
                    parser.get_mac(),
                    parser.get_name(),
                    parser.get_shutter_position(),
                    parser.get_shutter_direction(),
                )
            )

        elif device_type and device_type.category == DeviceCategory.THERMOSTAT:
            logger.debug("discovered a Breeze switcher device")
            device_callback(
                SwitcherThermostat(
                    device_type,
                    device_state,
                    parser.get_device_id(),
                    parser.get_ip_type2(),
                    parser.get_mac(),
                    parser.get_name(),
                    parser.get_thermostat_mode(),
                    parser.get_thermostat_temp(),
                    parser.get_thermostat_target_temp(),
                    parser.get_thermostat_fan_level(),
                    parser.get_thermostat_swing(),
                    parser.get_thermostat_remote_id(),
                )
            )
        else:
            warn("discovered an unknown switcher device")


@final
class SwitcherBridge:
    """Use for running a UDP client for bridging Switcher devices broadcast messages.

    Args:
        on_device: a callable to which every new SwitcherBase device found will be send.
        broadcast_ports: broadcast ports list, default for type 1 devices is 20002,
            default for type 2 devices is 20003

    """

    def __init__(
        self,
        on_device: Callable[[SwitcherBase], Any],
        broadcast_ports: list[int] = [SWITCHER_UDP_PORT_TYPE1, SWITCHER_UDP_PORT_TYPE2],
    ) -> None:
        """Initialize the switcher bridge."""
        self._on_device = on_device
        self._broadcast_ports = broadcast_ports
        self._is_running = False
        self._transports = {}  # type: Dict[int, Optional[BaseTransport]]

    async def __aenter__(self) -> "SwitcherBridge":
        """Enter SwitcherBridge asynchronous context manager."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Exit the SwitcherBridge asynchronous context manager."""
        await self.stop()

    async def start(self) -> None:
        """Create an asynchronous listener and start the bridge."""
        for broadcast_port in self._broadcast_ports:
            logger.info("starting the udp bridge on port %s", broadcast_port)
            protocol_factory = UdpClientProtocol(
                partial(_parse_device_from_datagram, self._on_device)
            )
            transport, protocol = await get_running_loop().create_datagram_endpoint(
                lambda: protocol_factory,
                local_addr=("0.0.0.0", broadcast_port),  # nosec
                family=AF_INET,
            )
            self._transports[broadcast_port] = transport
            logger.debug("udp bridge on port %s started", broadcast_port)

        self._is_running = True

    async def stop(self) -> None:
        """Stop the asynchronous bridge."""
        for broadcast_port in self._broadcast_ports:
            transport = self._transports.get(broadcast_port)

            if transport and not transport.is_closing():
                logger.info("stopping the udp bridge on port %s", broadcast_port)
                transport.close()
            else:
                logger.info("udp bridge on port %s not started", broadcast_port)

        self._is_running = False

    @property
    def is_running(self) -> bool:
        """bool: Return true if bridge is running."""
        return self._is_running


@final
class UdpClientProtocol(DatagramProtocol):
    """Implementation of the Asyncio UDP DatagramProtocol."""

    def __init__(self, on_datagram: Callable[[bytes], None]) -> None:
        """Initialize the protocol."""
        self.transport = None  # type: Optional[BaseTransport]
        self._on_datagram = on_datagram

    def connection_made(self, transport: BaseTransport) -> None:
        """Call on connection established."""
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple) -> None:
        """Call on datagram received."""
        self._on_datagram(data)

    def error_received(self, exc: Optional[Exception]) -> None:
        """Call on exception received."""
        if exc:
            logger.error(f"udp client received error {exc}")
        else:
            warn("udp client received error")

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Call on connection lost."""
        if exc:
            logger.critical(f"udp bridge lost its connection {exc}")
        else:
            logger.info("udp connection stopped")


@final
@dataclass(frozen=True)
class DatagramParser:
    """Utility class for parsing a datagram into various device properties."""

    message: bytes

    def is_switcher_originator(self) -> bool:
        """Verify the broadcast message had originated from a switcher device."""
        return hexlify(self.message)[0:4].decode() == "fef0" and (
            len(self.message) == 165
            or len(self.message) == 168  # Switcher Breeze
            or len(self.message) == 159  # Switcher Runner and RunnerMini
        )

    def get_ip_type1(self) -> str:
        """Extract the IP address from the type1 broadcast message (Heater, Plug)."""
        hex_ip = hexlify(self.message)[152:160]
        ip_addr = int(hex_ip[6:8] + hex_ip[4:6] + hex_ip[2:4] + hex_ip[0:2], 16)
        return inet_ntoa(pack("<L", ip_addr))

    def get_ip_type2(self) -> str:
        """Extract the IP address from the broadcast message (Breeze, Runners)."""
        hex_ip = hexlify(self.message)[154:162]
        ip_addr = int(hex_ip[0:2] + hex_ip[2:4] + hex_ip[4:6] + hex_ip[6:8], 16)
        return inet_ntoa(pack(">L", ip_addr))

    def get_mac(self) -> str:
        """Extract the MAC address from the broadcast message."""
        hex_mac = hexlify(self.message)[160:172].decode().upper()
        return (
            hex_mac[0:2]
            + ":"
            + hex_mac[2:4]
            + ":"
            + hex_mac[4:6]
            + ":"
            + hex_mac[6:8]
            + ":"
            + hex_mac[8:10]
            + ":"
            + hex_mac[10:12]
        )

    def get_name(self) -> str:
        """Extract the device name from the broadcast message."""
        return self.message[42:74].decode().rstrip("\x00")

    def get_device_id(self) -> str:
        """Extract the device id from the broadcast message."""
        return hexlify(self.message)[36:42].decode()

    def get_device_state(self) -> DeviceState:
        """Extract the device state from the broadcast message."""
        hex_device_state = hexlify(self.message)[266:268].decode()
        return (
            DeviceState.ON
            if hex_device_state == DeviceState.ON.value
            else DeviceState.OFF
        )

    def get_auto_shutdown(self) -> str:
        """Extract the auto shutdown value from the broadcast message."""
        hex_auto_shutdown_val = hexlify(self.message)[310:318]
        int_auto_shutdown_val_secs = int(
            hex_auto_shutdown_val[6:8]
            + hex_auto_shutdown_val[4:6]
            + hex_auto_shutdown_val[2:4]
            + hex_auto_shutdown_val[0:2],
            16,
        )
        return seconds_to_iso_time(int_auto_shutdown_val_secs)

    def get_power_consumption(self) -> int:
        """Extract the power consumption from the broadcast message."""
        hex_power_consumption = hexlify(self.message)[270:278]
        return int(hex_power_consumption[2:4] + hex_power_consumption[0:2], 16)

    def get_remaining(self) -> str:
        """Extract the time remains for the current execution."""
        hex_remaining_time = hexlify(self.message)[294:302]
        int_remaining_time_seconds = int(
            hex_remaining_time[6:8]
            + hex_remaining_time[4:6]
            + hex_remaining_time[2:4]
            + hex_remaining_time[0:2],
            16,
        )
        return seconds_to_iso_time(int_remaining_time_seconds)

    def get_device_type(self) -> DeviceType:
        """Extract the device type from the broadcast message."""
        hex_model = hexlify(self.message[74:76]).decode()
        devices = dict(map(lambda d: (d.hex_rep, d), DeviceType))
        return devices[hex_model]

    # Switcher Runner and Runner Mini methods

    def get_shutter_position(self) -> int:
        """Return the current position of the shutter 0 <= pos <= 100."""
        hex_pos = hexlify(self.message[135:137]).decode()
        return int(hex_pos[2:4]) + int(hex_pos[0:2], 16)

    def get_shutter_direction(self) -> ShutterDirection:
        """Return the current direction of the shutter (UP/DOWN/STOP)."""
        hex_direction = hexlify(self.message[137:139]).decode()
        directions = dict(map(lambda d: (d.value, d), ShutterDirection))
        return directions[hex_direction]

    # Switcher Breeze methods

    def get_thermostat_temp(self) -> float:
        """Return the current temp of the thermostat."""
        hex_temp = hexlify(self.message[135:137]).decode()
        return int(hex_temp[2:4] + hex_temp[0:2], 16) / 10

    def get_thermostat_state(self) -> DeviceState:
        """Return the current thermostat state."""
        hex_power = hexlify(self.message[137:138]).decode()
        return DeviceState.ON if hex_power == DeviceState.ON.value else DeviceState.OFF

    def get_thermostat_mode(self) -> ThermostatMode:
        """Return the current thermostat mode."""
        hex_mode = hexlify(self.message[138:139]).decode()
        states = dict(map(lambda s: (s.value, s), ThermostatMode))
        return ThermostatMode.COOL if hex_mode not in states else states[hex_mode]

    def get_thermostat_target_temp(self) -> int:
        """Return the current temp of the thermostat."""
        hex_temp = hexlify(self.message[139:140]).decode()
        return int(hex_temp, 16)

    def get_thermostat_fan_level(self) -> ThermostatFanLevel:
        """Return the current thermostat fan level."""
        hex_level = hexlify(self.message[140:141]).decode()
        states = dict(map(lambda s: (s.value, s), ThermostatFanLevel))
        return states[hex_level[0:1]]

    def get_thermostat_swing(self) -> ThermostatSwing:
        """Return the current thermostat fan swing."""
        hex_swing = hexlify(self.message[140:141]).decode()

        return (
            ThermostatSwing.OFF
            if hex_swing[1:2] == ThermostatSwing.OFF.value
            else ThermostatSwing.ON
        )

    def get_thermostat_remote_id(self) -> str:
        """Return the current thermostat remote."""
        return self.message[143:151].decode()
