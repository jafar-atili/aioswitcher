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

"""Switcher integration TCP socket API module test cases."""

from asyncio.streams import StreamReader, StreamWriter
from binascii import hexlify, unhexlify
from datetime import timedelta
from json import loads
from unittest.mock import AsyncMock, Mock, patch

import pytest_asyncio
from assertpy import assert_that
from pytest import fixture, mark, raises

from aioswitcher.api import (
    Command,
    SwitcherBreezeCommand,
    SwitcherBreezeRemote,
    SwitcherBreezeRemoteManager,
    SwitcherType1Api,
    SwitcherType2Api,
)
from aioswitcher.api.messages import (
    SwitcherBaseResponse,
    SwitcherGetSchedulesResponse,
    SwitcherLoginResponse,
    SwitcherShutterStateResponse,
    SwitcherStateResponse,
    SwitcherThermostatStateResponse,
)
from aioswitcher.device import (
    DeviceState,
    ThermostatFanLevel,
    ThermostatMode,
    ThermostatSwing,
)

device_id = "aaaaaa"
device_ip = "1.2.3.4"
pytestmark = mark.asyncio


@fixture
def writer_write():
    return Mock()


@fixture
def reader_mock():
    return AsyncMock(spec_set=StreamReader)


@fixture
def writer_mock(writer_write):
    writer = AsyncMock(spec_set=StreamWriter)
    writer.write = writer_write
    return writer


@pytest_asyncio.fixture
async def connected_api_type1(reader_mock, writer_mock):
    with patch("aioswitcher.api.open_connection", return_value=(reader_mock, writer_mock)):
        api = SwitcherType1Api(device_ip, device_id)
        await api.connect()
        yield api
        await api.disconnect()


@pytest_asyncio.fixture
async def connected_api_type2(reader_mock, writer_mock):
    with patch("aioswitcher.api.open_connection", return_value=(reader_mock, writer_mock)):
        api = SwitcherType2Api(device_ip, device_id)
        await api.connect()
        yield api
        await api.disconnect()


class MockResponse:
    """Mock response for the aiohttp response object."""

    def __init__(self, text, status):
        """Initialize the aiohttp response object."""
        self._text = text
        self.status = status
        self.content_length = len(self._text)

    async def text(self):
        """Text data of the response class mock."""
        return self._text

    async def json(self, content_type=None):
        """Json method of the response class mock."""
        return loads(self._text)

    async def __aexit__(self, exc_type, exc, tb):
        """Magic method when starting an async block."""
        pass

    async def __aenter__(self):
        """Magic method when leaving an async block."""
        return self


@patch("logging.Logger.info")
async def test_stopping_before_started_and_connected_should_write_to_the_info_output(mock_info):
    api = SwitcherType1Api(device_ip, device_id)
    assert_that(api.connected).is_false()
    await api.disconnect()
    mock_info.assert_called_with("switcher device not connected")


async def test_api_as_a_context_manager(reader_mock, writer_mock):
    with patch("aioswitcher.api.open_connection", return_value=(reader_mock, writer_mock)):
        async with SwitcherType1Api(device_ip, device_id) as api:
            assert_that(api.connected).is_true()


async def test_login_function(reader_mock, writer_write, connected_api_type1, resource_path_root):
    response_packet = _load_packet(resource_path_root, "login_response")
    with patch.object(reader_mock, "read", return_value=response_packet):
        response = await connected_api_type1._login()
    writer_write.assert_called_once()
    assert_that(response[1]).is_instance_of(SwitcherLoginResponse)
    assert_that(response[1].unparsed_response).is_equal_to(response_packet)


async def test_login2_function(reader_mock, writer_write, connected_api_type2, resource_path_root):
    response_packet = _load_packet(resource_path_root, "login2_response")
    with patch.object(reader_mock, "read", return_value=response_packet):
        response = await connected_api_type2._login()
    writer_write.assert_called_once()
    assert_that(response[1]).is_instance_of(SwitcherLoginResponse)
    assert_that(response[1].unparsed_response).is_equal_to(response_packet)


async def test_get_state_function_with_a_faulty_login_response_should_raise_error(reader_mock, writer_write, connected_api_type1):
    with raises(RuntimeError, match="login request was not successful"):
        with patch.object(reader_mock, "read", return_value=b''):
            await connected_api_type1.get_state()
    writer_write.assert_called_once()


async def test_get_state_function_with_a_faulty_get_state_response_should_raise_error(reader_mock, writer_write, connected_api_type1, resource_path_root):
    login_response_packet = _load_packet(resource_path_root, "login_response")
    with raises(RuntimeError, match="get state request was not successful"):
        with patch.object(reader_mock, "read", side_effect=[login_response_packet, b'']):
            await connected_api_type1.get_state()
    assert_that(writer_write.call_count).is_equal_to(2)


async def test_get_state_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    login_response_packet = _load_packet(resource_path_root, "login_response")
    get_state_response_packet = _load_packet(resource_path_root, "get_state_response")
    with patch.object(reader_mock, "read", side_effect=[login_response_packet, get_state_response_packet]):
        response = await connected_api_type1.get_state()
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherStateResponse)
    assert_that(response.unparsed_response).is_equal_to(get_state_response_packet)


async def test_get_breeze_state_function_with_valid_packets(reader_mock, writer_write, connected_api_type2, resource_path_root):
    login_response_packet = _load_packet(resource_path_root, "login2_response")
    get_breeze_state_response_packet = _load_packet(resource_path_root, "get_breeze_state")
    with patch.object(reader_mock, "read", side_effect=[login_response_packet, get_breeze_state_response_packet]):
        response = await connected_api_type2.get_breeze_state()
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherThermostatStateResponse)
    assert_that(response.unparsed_response).is_equal_to(get_breeze_state_response_packet)


async def test_turn_on_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "turn_on_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.control_device(Command.ON)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_get_breeze_state_function_with_a_faulty_login_response_should_raise_error(reader_mock, writer_write, connected_api_type2):
    with raises(RuntimeError, match="login request was not successful"):
        with patch.object(reader_mock, "read", return_value=b''):
            await connected_api_type2.get_breeze_state()
    writer_write.assert_called_once()


async def test_get_breeze_state_function_with_a_faulty_get_state_response_should_raise_error(reader_mock, writer_write, connected_api_type2, resource_path_root):
    login_response_packet = _load_packet(resource_path_root, "login_response")
    with raises(RuntimeError, match="get breeze state request was not successful"):
        with patch.object(reader_mock, "read", side_effect=[login_response_packet, b'']):
            await connected_api_type2.get_breeze_state()
    assert_that(writer_write.call_count).is_equal_to(2)


async def test_control_breeze_device_function_with_valid_packets(reader_mock, writer_write, connected_api_type2, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "control_breeze_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        remote = SwitcherBreezeRemoteManager().get_remote('ELEC7022')
        command: SwitcherBreezeCommand = remote.get_command(DeviceState.ON, ThermostatMode.COOL, 24, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.OFF)
        response = await connected_api_type2.control_breeze_device(command)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_breeze_remote_min_max_temp():
    remote = SwitcherBreezeRemoteManager().get_remote('ELEC7001')
    max_temp = remote.max_temperature
    min_temp = remote.min_temperature
    assert_that(min_temp).is_equal_to(16)
    assert_that(min_temp).is_instance_of(int)
    assert_that(max_temp).is_equal_to(30)
    assert_that(max_temp).is_instance_of(int)


async def test_breeze_get_remote_id():
    remote = SwitcherBreezeRemoteManager().get_remote('ELEC7001')
    remote_id = remote.remote_id
    assert_that(remote_id).is_equal_to("ELEC7001")
    assert_that(remote_id).is_instance_of(str)


async def test_control_breeze_function_with_a_faulty_get_state_response_should_raise_error(reader_mock, writer_write, connected_api_type2):
    with raises(RuntimeError, match="login request was not successful"):
        remote = SwitcherBreezeRemoteManager().get_remote('ELEC7022')
        command: SwitcherBreezeCommand = remote.get_command(DeviceState.ON, ThermostatMode.COOL, 24, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.OFF)
        with patch.object(reader_mock, "read", return_value=b''):
            await connected_api_type2.control_breeze_device(command)
    writer_write.assert_called_once()


async def test_get_breeze_command_function_with_low_temp(reader_mock, writer_write, connected_api_type2, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "control_breeze_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        remote = SwitcherBreezeRemoteManager().get_remote('ELEC7022')
        command: SwitcherBreezeCommand = remote.get_command(DeviceState.ON, ThermostatMode.COOL, 10, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.OFF)
        response = await connected_api_type2.control_breeze_device(command)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_get_breeze_command_function_with_high_temp(reader_mock, writer_write, connected_api_type2, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "control_breeze_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        remote = SwitcherBreezeRemoteManager().get_remote('ELEC7022')
        command: SwitcherBreezeCommand = remote.get_command(DeviceState.ON, ThermostatMode.COOL, 100, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.OFF)
        response = await connected_api_type2.control_breeze_device(command)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_breeze_get_command_function_with_non_supported_mode(resource_path_root):
    # test invalid non existing mode (cool)
    brm = SwitcherBreezeRemoteManager(str(resource_path_root) + "/breeze_data/irset_db_invalid_elec7022_data.json")
    remote = brm.get_remote('ELEC7022')
    with raises(RuntimeError, match=f"Invalid mode \"{ThermostatMode.COOL.display}\", available modes for this device are: {', '.join([x.display for x in remote.supported_modes])}"):
        remote.get_command(DeviceState.ON, ThermostatMode.COOL, 20, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.OFF)


async def test_breeze_get_command_function_non_toggle_type_off_state(resource_path_root):
    elec7022_turn_off_cmd = unhexlify((resource_path_root / ("breeze_data/" + "breeze_elec7022_turn_off_command" + ".txt")).read_text().replace('\n', '').encode())
    remote = SwitcherBreezeRemoteManager().get_remote('ELEC7022')
    command = remote.get_command(DeviceState.OFF, ThermostatMode.DRY, 20, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.OFF)
    assert_that(command).is_instance_of(SwitcherBreezeCommand)
    assert_that(command.command).is_equal_to(hexlify(elec7022_turn_off_cmd).decode())


async def test_breeze_get_command_function_toggle_type(resource_path_root):
    elec7001_turn_off_cmd = unhexlify((resource_path_root / ("breeze_data/" + "breeze_elec7001_turn_off_command" + ".txt")).read_text().replace('\n', '').encode())

    remote = SwitcherBreezeRemoteManager().get_remote('ELEC7001')
    command = remote.get_command(DeviceState.OFF, ThermostatMode.DRY, 20, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.ON)
    assert_that(command).is_instance_of(SwitcherBreezeCommand)
    assert_that(command.command).is_equal_to(hexlify(elec7001_turn_off_cmd).decode())


async def test_breeze_get_command_function_should_raise_command_does_not_eixst(resource_path_root):
    elec7001_turn_off_cmd = unhexlify((resource_path_root / ("breeze_data/" + "breeze_elec7001_turn_off_command" + ".txt")).read_text().replace('\n', '').encode())

    remote = SwitcherBreezeRemoteManager().get_remote('ELEC7001')
    command = remote.get_command(DeviceState.OFF, ThermostatMode.DRY, 20, ThermostatFanLevel.HIGH, ThermostatSwing.ON, DeviceState.ON)
    assert_that(command).is_instance_of(SwitcherBreezeCommand)
    assert_that(command.command).is_equal_to(hexlify(elec7001_turn_off_cmd).decode())


async def test_breeze_remote_manager_with_none_existing_remotes_db():
    local_remotes_db = "/wrong/directory/remotes_db.json"
    with raises(OSError, match=f"The specified remote db path {local_remotes_db} does not exist"):
        SwitcherBreezeRemoteManager(local_remotes_db)


async def test_breeze_remote_manager_get_from_local_database():
    remote_manager = SwitcherBreezeRemoteManager()
    remote_7022 = remote_manager.get_remote("ELEC7022")
    assert_that(remote_7022).is_type_of(SwitcherBreezeRemote)
    assert_that(remote_7022.remote_id).is_equal_to("ELEC7022")


async def test_breeze_get_swing_command():
    remote_manager = SwitcherBreezeRemoteManager()
    remote_7022 = remote_manager.get_remote("ELEC7022")
    command = remote_7022.get_swing_command(swing=ThermostatSwing.ON)
    assert_that(command.command).is_equal_to("000000004e4543587c32367c33327c31352c31357c31352c34307c31357c54303043387c33307c30317c414241425b33305d7c423234443642393445303146")


async def test_breeze_get_swing_command_on_wrong_remote():
    remote_manager = SwitcherBreezeRemoteManager()
    remote_7001 = remote_manager.get_remote("ELEC7001")
    with raises(RuntimeWarning, match=f"Swing special function doesn't apply on this remote {remote_7001.remote_id}"):
        remote_7001.get_swing_command(swing=ThermostatSwing.ON)


async def test_breeze_get_swing_command_on_invalid_remote(resource_path_root):
    brm = SwitcherBreezeRemoteManager(str(resource_path_root) + "/breeze_data/irset_db_invalid_elec7022_data.json")
    remote_7022 = brm.get_remote('ELEC7022')
    with raises(RuntimeError):
        remote_7022.get_swing_command(swing=ThermostatSwing.ON)


async def test_breeze_get_command_function_invalid_mode(resource_path_root):
    brm = SwitcherBreezeRemoteManager(str(resource_path_root) + "/breeze_data/irset_db_invalid_elec7022_data.json")
    remote = brm.get_remote('ELEC7022')
    with raises(RuntimeError, match="Invalid mode \"cool\", available modes for this device are: auto, dry, fan"):
        remote.get_command(DeviceState.ON, ThermostatMode.COOL, 20, ThermostatFanLevel.AUTO, ThermostatSwing.ON, DeviceState.OFF)


async def test_turn_on_with_timer_function_with_valid_packets(reader_mock, writer_write, resource_path_root, connected_api_type2):
    two_packets = _get_two_packets(resource_path_root, "turn_on_with_timer_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type2.control_device(Command.ON, 15)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_turn_off_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "turn_off_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.control_device(Command.OFF)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_set_name_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "set_name_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.set_device_name("my boiler")
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_set_auto_shutdown_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "set_auto_shutdown_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.set_auto_shutdown(timedelta(hours=2, minutes=30))
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_get_schedules_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "get_schedules_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.get_schedules()
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherGetSchedulesResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_delete_schedule_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "delete_schedule_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.delete_schedule("0")
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_create_schedule_function_with_valid_packets(reader_mock, writer_write, connected_api_type1, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "create_schedule_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type1.create_schedule("18:00", "19:00")
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_stop_shutter_device_function_with_valid_packets(reader_mock, writer_write, connected_api_type2, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "stop_shutter_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type2.stop()
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_set_shutter_position_device_function_with_valid_packets(reader_mock, writer_write, connected_api_type2, resource_path_root):
    two_packets = _get_two_packets(resource_path_root, "set_shutter_position_response")
    with patch.object(reader_mock, "read", side_effect=two_packets):
        response = await connected_api_type2.set_position(50)
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherBaseResponse)
    assert_that(response.unparsed_response).is_equal_to(two_packets[-1])


async def test_get_shutter_state_function_with_valid_packets(reader_mock, writer_write, connected_api_type2, resource_path_root):
    login_response_packet = _load_packet(resource_path_root, "login2_response")
    get_state_response_packet = _load_packet(resource_path_root, "get_shutter_state_response")
    with patch.object(reader_mock, "read", side_effect=[login_response_packet, get_state_response_packet]):
        response = await connected_api_type2.get_shutter_state()
    assert_that(writer_write.call_count).is_equal_to(2)
    assert_that(response).is_instance_of(SwitcherShutterStateResponse)
    assert_that(response.unparsed_response).is_equal_to(get_state_response_packet)


async def test_get_shutter_state_function_with_a_faulty_login_response_should_raise_error(reader_mock, writer_write, connected_api_type2):
    with raises(RuntimeError, match="login request was not successful"):
        with patch.object(reader_mock, "read", return_value=b''):
            await connected_api_type2.get_shutter_state()
    writer_write.assert_called_once()


async def test_get_shutter_state_function_with_a_faulty_get_state_response_should_raise_error(reader_mock, writer_write, connected_api_type2, resource_path_root):
    login_response_packet = _load_packet(resource_path_root, "login_response")
    with raises(RuntimeError, match="get shutter state request was not successful"):
        with patch.object(reader_mock, "read", side_effect=[login_response_packet, b'']):
            await connected_api_type2.get_shutter_state()
    assert_that(writer_write.call_count).is_equal_to(2)


async def test_set_position_function_with_a_faulty_get_state_response_should_raise_error(reader_mock, writer_write, connected_api_type2):
    with raises(RuntimeError, match="login request was not successful"):
        with patch.object(reader_mock, "read", return_value=b''):
            await connected_api_type2.set_position(50)
    writer_write.assert_called_once()


async def test_stop_position_function_with_a_faulty_get_state_response_should_raise_error(reader_mock, writer_write, connected_api_type2):
    with raises(RuntimeError, match="login request was not successful"):
        with patch.object(reader_mock, "read", return_value=b''):
            await connected_api_type2.stop()
    writer_write.assert_called_once()


def _get_two_packets(resource_path_root, second_packet):
    return [
        _load_packet(resource_path_root, "login_response"),
        _load_packet(resource_path_root, second_packet),
    ]


def _load_packet(path, file_name):
    return unhexlify((path / ("dummy_responses/" + file_name + ".txt")).read_text().replace('\n', '').encode())
