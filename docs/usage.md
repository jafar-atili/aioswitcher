
# Usage

## Bridge

We can use the Bridge implementation to discover devices and their state.
The following code will print all discovered devices for 60 seconds.

```python
async def print_devices(delay):
    def on_device_found_callback(device):
        print(asdict(device)) # (1)

    async with SwitcherBridge(on_device_found_callback):
        await asyncio.sleep(delay)

asyncio.get_event_loop().run_until_complete(print_devices(60))
```

1. the callback device will be an implementation of [SwitcherBase](./codedocs.md#src.aioswitcher.device.SwitcherBase),
    i.e. [SwitcherPowerPlug](./codedocs.md#src.aioswitcher.device.SwitcherPowerPlug),
    [SwitcherWaterHeater](./codedocs.md#src.aioswitcher.device.SwitcherWaterHeater),
    [SwitcherThermostat](./codedocs.md#src.aioswitcher.device.SwitcherThermostat), and
    [SwitcherShutter](./codedocs.md#src.aioswitcher.device.SwitcherShutter).

!!!note
    A Switcher device will broadcast a state message to the bridge approximately every 4 seconds.

## API

### Type1 API (Switcher Plug, V2, Touch, V4)

We can use the Type1 API to gain the following capabilities:

- Get the current state
- Turn on and off
- Set the name
- Configure auto shutdown
- Retrieve the schedules
- Create and Delete schedules

```python
async def control_device(device_ip, device_id) :
    # for connecting to a device we need its id and ip address
    async with SwitcherType1Api(device_ip, device_id) as api:
        # get the device current state (1)
        await api.get_state()
        # turn the device on for 15 minutes (2)
        await api.control_device(Command.ON, 15)
        # turn the device off (3)
        await api.control_device(Command.OFF)
        # set the device name to 'my new name' (4)
        await api.set_device_name("my new name")
        # configure the device for 02:30 auto shutdown (5)
        await api.set_auto_shutdown(timedelta(hours=2, minutes=30))
        # get the schedules from the device (6)
        await api.get_schedules()
        # delete and existing schedule with id 1 (7)
        await api.delete_schedule("1")
        # create a new recurring schedule for 13:00-14:30
        # executing on sunday and friday (8)
        await api.create_schedule("13:00", "14:30", {Days.SUNDAY, Days.FRIDAY})

asyncio.get_event_loop().run_until_complete(
    control_device("111.222.11.22", "ab1c2d")
)
```

1. [SwitcherStateResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherStateResponse)
2. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
3. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
4. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
5. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
6. [SwitcherGetSchedulesResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherGetSchedulesResponse)
7. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
8. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)

### Type2 API (Switcher Breeze and Runner)

We can use the Type2 API to gain the following capabilities on Switcher Breeze and Runner:

- Get the current state
- Control Runner position
- Control Breeze (State, Mode, Fan Level, Target Temperature, Vertical Swing)

```python
async def control_runner(device_ip, device_id) :
    # for connecting to a device we need its id and ip address
    async with SwitcherType2Api(device_ip, device_id) as api:
        # get the device current state (1)
        await api.get_shutter_state()
        # open the shutter to 30% (2)
        await api.set_position(30)
        # stop the shutter if currently rolling (3)
        await api.stop()

asyncio.get_event_loop().run_until_complete(
    control_runner("111.222.11.22", "ab1c2d")
)
```

1. [SwitcherShutterStateResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherShutterStateResponse)
2. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
3. [SwitcherShutterStateResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherShutterStateResponse)

```python
async def control_breeze(device_ip, device_id, remote_manager, remote_id) :
    # for connecting to a device we need its id and ip address
    async with SwitcherType2Api(device_ip, device_id) as api:
        # get the device current state (1)
        await api.get_breeze_state()
        # initialize the Breeze RemoteManager and get the remote (2)
        remote = remote_manager.get_remote(remote_id)
        # prepare a control command that turns on the Breeze
        # set to 24 degree (Celsius) cooling with vertical swing
        # and keep the current Fan Level (3)
        command: SwitcherBreezeCommand = remote.get_command(
            DeviceState.ON,
            ThermostatMode.COOL,
            24,
            resp.fan_level,
            ThermostatSwing.ON,
            response.state
        )
        # send command to the device (4)
        await api.control_breeze_device(command)

# create the remote manager outside the context for re-using (5)
remote_manager = SwitcherBreezeRemoteManager()
asyncio.get_event_loop().run_until_complete(
    control_breeze("111.222.11.22", "ab1c2d", remote_manager, "DLK65863")
)
```

1. [SwitcherThermostatStateResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherThermostatStateResponse)
2. [SwitcherBreezeRemote](./codedocs.md#src.aioswitcher.api.messages.SwitcherBreezeRemote)
3. [SwitcherBreezeCommand](./codedocs.md#src.aioswitcher.api.SwitcherBreezeCommand)
4. [SwitcherBaseResponse](./codedocs.md#src.aioswitcher.api.messages.SwitcherBaseResponse)
5. [SwitcherBreezeRemoteManager](./codedocs.md#src.aioswitcher.api.SwitcherBreezeRemoteManager)

!!! info
    You can find the supported device types stated in [this enum](./codedocs.md#src.aioswitcher.device.DeviceType) members.
