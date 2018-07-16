import asyncio
import logging
from functools import partial

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


class NADC338Protocol(asyncio.Protocol):
    AVAILABLE_SOURCES = COMMAND_SCHEMA[CMD_SOURCE]['values']

    PORT = 30001

    transport = None  # type: asyncio.Transport

    def __init__(self, loop=None, state_changed_cb=None, disconnect_cb=None) -> None:
        self._loop = loop
        self._buffer = ''
        self._state = {}

        self._state_waiter = None
        self._state_changed_cb = state_changed_cb
        self._disconnect_cb = disconnect_cb

    def connection_made(self, transport):
        self.transport = transport
        _LOGGER.debug("connected")

    def data_received(self, data):
        data = data.decode('utf-8').replace('\x00', '')

        _LOGGER.debug('received data: %s', data)

        self._buffer += data

        self._drain_buffer()

    def connection_lost(self, exc):
        if exc:
            _LOGGER.error(exc, exc_info=True)
        else:
            _LOGGER.info('disconnected because of close/abort.')
        if self._disconnect_cb:
            self._disconnect_cb(exc)

    def _drain_buffer(self):
        new_state = {}

        while '\r\n' in self._buffer:
            line, self._buffer = self._buffer.split('\r\n', 1)

            key, value = line.split('=')

            if 'type' in COMMAND_SCHEMA[key]:
                value = COMMAND_SCHEMA[key]['type'](value)

            new_state[key] = value

        if new_state:
            self._state.update(new_state)

            if self._state_waiter is not None and \
                    len(self._state) == len(COMMAND_SCHEMA) - 1:
                self._state_waiter.set_result(True)

            if self._state_changed_cb:
                self._state_changed_cb(self._state)

    def _send(self, data: str):
        _LOGGER.debug('writing data: %s', repr(data))
        packet = data + '\r\n'
        self.transport.write(packet.encode('utf-8'))

    def _exec_command(self, command, operator, value=None):
        cmd_desc = COMMAND_SCHEMA[command]
        if operator in cmd_desc['supported_operators']:
            if operator is '=' and value is None:
                raise ValueError("No value provided")
            elif operator in ['?', '-', '+'] and value is not None:
                raise ValueError("Operator \'%s\' cannot be called with a value" % operator)

            if value is None:
                cmd = command + operator
            else:
                if 'values' in cmd_desc and value not in cmd_desc['values']:
                    raise ValueError("Given value \'%s\' is not one of %s" % (value, cmd_desc['values']))

                cmd = command + operator + str(value)
        else:
            raise ValueError("Invalid operator provided %s" % operator)

        self._send(cmd)

    async def state(self, force_refresh=False, timeout=1):
        """Return the state of the device."""

        if force_refresh:
            self._state_waiter = self._loop.create_future()
            self._state.clear()

            self._exec_command(CMD_MAIN, '?')

            try:
                with async_timeout.timeout(timeout, loop=self._loop):
                    await self._state_waiter
            finally:
                self._state_waiter = None

        return self._state

    def power_off(self):
        """Power the device off."""
        self._exec_command(CMD_POWER, '=', MSG_OFF)

    def power_on(self):
        """Power the device on."""
        self._exec_command(CMD_POWER, '=', MSG_ON)

    def set_volume(self, volume):
        """Set volume level of the device. Accepts integer values 0-200."""
        self._exec_command(CMD_VOLUME, '=', float(volume))

    def volume_down(self):
        self._exec_command(CMD_VOLUME, '-')

    def volume_up(self):
        self._exec_command(CMD_VOLUME, '+')

    def mute(self):
        """Mute the device."""
        self._exec_command(CMD_MUTE, '=', MSG_ON)

    def unmute(self):
        """Unmute the device."""
        self._exec_command(CMD_MUTE, '=', MSG_OFF)

    def select_source(self, source):
        """Select a source from the list of sources."""
        self._exec_command(CMD_SOURCE, '=', source)

    def available_sources(self):
        """Return a list of available sources."""
        return list(self.AVAILABLE_SOURCES)

    @staticmethod
    def create_nad_connection(loop, target_ip, state_changed_cb=None, disconnect_cb=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        _LOGGER.debug("Initializing nad connection to %s", target_ip)

        protocol = partial(
            NADC338Protocol,
            loop=loop,
            state_changed_cb=state_changed_cb,
            disconnect_cb=disconnect_cb
        )

        return loop.create_connection(protocol, target_ip, NADC338Protocol.PORT)
