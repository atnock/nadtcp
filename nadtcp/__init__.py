import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

CMD_MAIN = "Main"
CMD_BRIGHTNESS = "Main.Brightness"
CMD_BASS_EQ = "Main.Bass"
CMD_CONTROL_STANDBY = "Main.ControlStandby"
CMD_AUTO_STANDBY = "Main.AutoStandby"
CMD_VERSION = "Main.Version"
CMD_MUTE = "Main.Mute"
CMD_POWER = "Main.Power"
CMD_AUTO_SENSE = "Main.AutoSense"
CMD_SOURCE = "Main.Source"
CMD_VOLUME = "Main.Volume"

MSG_ON = 'On'
MSG_OFF = 'Off'

COMMAND_SCHEMA = {
    'Main':
        {'supported_operators': ['?']
         },
    'Main.AnalogGain':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(0, 0),
         'type': int
         },
    'Main.Brightness':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(0, 4),
         'type': int
         },
    'Main.Mute':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_ON, MSG_OFF]
         },
    'Main.Power':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_ON, MSG_OFF]
         },
    'Main.Volume':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(-80, 0),
         'type': float
         },
    'Main.Bass':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_ON, MSG_OFF],
         },
    'Main.ControlStandby':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_ON, MSG_OFF]
         },
    'Main.AutoStandby':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_ON, MSG_OFF]
         },
    'Main.AutoSense':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_ON, MSG_OFF]
         },
    'Main.Source':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': ["Stream", "Wireless", "TV", "Phono", "Coax1", "Coax2", "Opt1", "Opt2"]
         },
    'Main.Version':
        {'supported_operators': ['?'],
         'type': float
         },
    'Main.Model':
        {'supported_operators': ['?'],
         'values': ['NADC338']
         }
}


class NADC338Client(object):
    AVAILABLE_SOURCES = COMMAND_SCHEMA[CMD_SOURCE]['values']

    PORT = 30001

    def __init__(self, host, loop,
                 reconnect_timeout=10,
                 state_batching_timeout=0.1,
                 state_changed_cb=None) -> None:
        self._host = host
        self._loop = loop
        self._reconnect_timeout = reconnect_timeout

        self._state_changed_cb = state_changed_cb
        self._state_batching_timeout = state_batching_timeout

        self._reader = None
        self._writer = None

        self._connection_loop_ft = None
        self._state_changed_waiter = None

        self._state = {}

    async def _state_changed_batch(self):
        await asyncio.sleep(self._state_batching_timeout)
        self._state_changed_cb(self._state)
        self._state_changed_waiter = None

    def _parse_data(self, data):
        key, value = data.split('=')

        if 'type' in COMMAND_SCHEMA[key]:
            value = COMMAND_SCHEMA[key]['type'](value)

        old_value = self._state.get(key)

        if value != old_value:
            _LOGGER.debug("State changed %s=%s", key, value)
            
            self._state[key] = value

            if self._state_changed_cb and self._state_changed_waiter is None:
                self._state_changed_waiter = asyncio.ensure_future(
                    self._state_changed_batch(), loop=self._loop)

    async def _connection_loop(self):
        try:
            self._reader, self._writer = await asyncio.open_connection(self._host, self.PORT, loop=self._loop)
            self.exec_command('Main', '?')

            while self._reader and not self._reader.at_eof():
                data = await self._reader.readline()
                if data:
                    self._parse_data(data.decode('utf-8').strip())
        finally:
            if self._state_changed_waiter and not self._state_changed_waiter.done():
                self._state_changed_waiter.cancel()

            self._writer = None
            self._reader = None

            if self._state:
                self._state.clear()

                if self._state_changed_cb:
                    self._state_changed_cb(self._state)

    async def disconnect(self):
        _LOGGER.debug("Disconnecting from %s", self._host)

        if self._writer:
            # send EOF, let the connection exit gracefully
            if self._writer.can_write_eof():
                _LOGGER.debug("Disconnect: writing EOF")
                self._writer.write_eof()
            # socket cannot send EOF, cancel connection
            elif self._connection_loop:
                _LOGGER.debug("Disconnect: force")
                self._connection_loop_ft.cancel()

            await self._connection_loop_ft

    async def run_loop(self):
        while True:
            _LOGGER.debug("Connecting to %s", self._host)
            self._connection_loop_ft = asyncio.ensure_future(
                self._connection_loop(), loop=self._loop)
            try:
                await self._connection_loop_ft
                # EOF reached, break reconnect loop
                _LOGGER.debug("EOF reached")
                break
            except asyncio.CancelledError:
                # force disconnect, break reconnect loop
                _LOGGER.debug("Force disconnect")
                break
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
                _LOGGER.exception("Disconnected, reconnecting in %ss", self._reconnect_timeout, exc_info=e)
                await asyncio.sleep(self._reconnect_timeout)

    def exec_command(self, command, operator, value=None):
        if self._writer:
            cmd_desc = COMMAND_SCHEMA[command]
            if operator in cmd_desc['supported_operators']:
                if operator is '=' and value is None:
                    raise ValueError("No value provided")
                elif operator in ['?', '-', '+'] and value is not None:
                    raise ValueError(
                        "Operator \'%s\' cannot be called with a value" % operator)

                if value is None:
                    cmd = command + operator
                else:
                    if 'values' in cmd_desc and value not in cmd_desc['values']:
                        raise ValueError("Given value \'%s\' is not one of %s" % (
                            value, cmd_desc['values']))

                    cmd = command + operator + str(value)
            else:
                raise ValueError("Invalid operator provided %s" % operator)

            self._writer.write(cmd.encode('utf-8'))

    def power_off(self):
        """Power the device off."""
        self.exec_command(CMD_POWER, '=', MSG_OFF)

    def power_on(self):
        """Power the device on."""
        self.exec_command(CMD_POWER, '=', MSG_ON)

    def set_volume(self, volume):
        """Set volume level of the device. Accepts integer values 0-200."""
        self.exec_command(CMD_VOLUME, '=', float(volume))

    def volume_down(self):
        self.exec_command(CMD_VOLUME, '-')

    def volume_up(self):
        self.exec_command(CMD_VOLUME, '+')

    def mute(self):
        """Mute the device."""
        self.exec_command(CMD_MUTE, '=', MSG_ON)

    def unmute(self):
        """Unmute the device."""
        self.exec_command(CMD_MUTE, '=', MSG_OFF)

    def select_source(self, source):
        """Select a source from the list of sources."""
        self.exec_command(CMD_SOURCE, '=', source)

    def available_sources(self):
        """Return a list of available sources."""
        return list(self.AVAILABLE_SOURCES)