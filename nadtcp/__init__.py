import asyncio
import socket
import logging
import time

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

C338_CMDS = {
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
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.Power':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.Volume':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(-80, 0),
         'type': float
         },
    'Main.Bass':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.ControlStandby':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.AutoStandby':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.AutoSense':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
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


class NADReceiverTCPC338(object):
    """
    Support NAD amplifiers that use tcp for communication.

    Known supported model: NAD C338.
    """

    PORT = 30001

    CMD_MIN_INTERVAL = 0.15

    def __init__(self, host, loop,
                 reconnect_timeout=10,
                 state_changed_cb=None):
        self._host = host
        self._loop = loop

        self._reconnect_timeout = reconnect_timeout
        self._state_changed_cb = state_changed_cb

        self._reader, self._writer = None, None

        self._connection_task = None

        self.last_cmd_time = 0

        self._state = {}

    @staticmethod
    def make_command(command, operator, value=None):
        cmd_desc = C338_CMDS[command]
        # validate operator
        if operator in cmd_desc['supported_operators']:
            if operator is '=' and value is None:
                raise ValueError("No value provided")
            elif operator in ['?', '-', '+'] and value is not None:
                raise ValueError(
                    "Operator \'%s\' cannot be called with a value" % operator)

            if value is None:
                cmd = command + operator
            else:
                # validate value
                if 'values' in cmd_desc:
                    if 'type' in cmd_desc and cmd_desc['type'] == bool:
                        value = cmd_desc['values'][int(value)]
                    elif value not in cmd_desc['values']:
                        raise ValueError("Given value \'%s\' is not one of %s" % (
                            value, cmd_desc['values']))

                cmd = command + operator + str(value)
        else:
            raise ValueError("Invalid operator provided %s" % operator)

        return cmd

    def _state_changed(self):
        if self._state_changed_cb:
            self._state_changed_cb(self._state)

    def _update_state(self, data):
        _LOGGER.debug("Received data %s", data)

        data = data.decode('utf-8').replace('\x00', '').strip()

        key, value = data.split('=')
        cmd_desc = C338_CMDS[key]

        # convert the data to the correct type
        if 'type' in cmd_desc:
            if cmd_desc['type'] == bool:
                value = bool(cmd_desc['values'].index(value))
            else:
                value = cmd_desc['type'](value)

        self._state[key] = value

        # volume changes implicitly disables mute, after min volume it mutes, but we don't get any data for that...
        if key == 'Main.Volume':
            self._state['Main.Mute'] = False

        self._state_changed()

    async def connect(self):
        if self._connection_task is None:
            self._connection_task = self._loop.create_task(self._connection_loop())

    async def disconnect(self):
        """Disconnect from the device."""
        if self._writer:
            _LOGGER.debug("Disconnecting from %s", self._host)
            # send EOF, let the connection exit gracefully
            if self._writer.can_write_eof():
                _LOGGER.debug("Disconnect: writing EOF")
                self._writer.write_eof()
            # socket cannot send EOF, cancel connection
            elif self._connection_task:
                _LOGGER.debug("Disconnect: force")
                self._connection_task.cancel()

            await self._connection_task

    async def _connect(self):
        _LOGGER.debug("Connecting to %s", self._host)
        self._reader, self._writer = await asyncio.open_connection(self._host, self.PORT, loop=self._loop)

        sock = self._writer.transport.get_extra_info('socket')
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 1)
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, 10)
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 3)

    async def _read_until_eof(self):
        while self._reader and not self._reader.at_eof():
            data = await self._reader.readline()
            if data:
                self._update_state(data)

    async def _connection_loop(self):
        """Start the connection loop which handles reconnects."""
        while True:
            try:
                await self._connect()
                await self.exec_command('Main', '?')
                await self._read_until_eof()
                # EOF reached, break reconnect loop
                _LOGGER.debug("EOF reached")
                break
            except asyncio.CancelledError:
                # force disconnect, break reconnect loop
                _LOGGER.debug("Force disconnect")
                break
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
                _LOGGER.exception("Disconnected, reconnecting in %ss",
                                  self._reconnect_timeout, exc_info=e)
                await asyncio.sleep(self._reconnect_timeout)
            finally:
                self._writer, self._reader = None, None
                self._state.clear()
                self._state_changed()

    async def exec_command(self, command, operator, value=None):
        """Execute a command on the device."""
        if self._writer:
            # throttle commands to CMD_MIN_INTERVAL
            cmd_wait_time = (self.last_cmd_time + self.CMD_MIN_INTERVAL) - time.time()
            if cmd_wait_time > 0:
                await asyncio.sleep(cmd_wait_time)

            cmd = self.make_command(command, operator, value)
            self._writer.write(cmd.encode('utf-8'))

            self.last_cmd_time = time.time()

    async def status(self):
        """
        Return the status of the device.

        Returns a dictionary with keys 'Main.Volume' (int -80-0) , 'Main.Power' (bool),
         'Main.Mute' (bool) and 'Main.Source' (str).
        """
        return self._state

    async def power_off(self):
        """Power the device off."""
        await self.exec_command(CMD_POWER, '=', False)

    async def power_on(self):
        """Power the device on."""
        await self.exec_command(CMD_POWER, '=', True)

    async def set_volume(self, volume):
        """Set volume level of the device in dBa. Accepts integer values -80-0."""
        await self.exec_command(CMD_VOLUME, '=', float(volume))

    async def volume_down(self):
        """Decrease the volume of the device."""
        await self.exec_command(CMD_VOLUME, '-')

    async def volume_up(self):
        """Increase the volume of the device."""
        await self.exec_command(CMD_VOLUME, '+')

    async def mute(self):
        """Mute the device."""
        await self.exec_command(CMD_MUTE, '=', True)

    async def unmute(self):
        """Unmute the device."""
        await self.exec_command(CMD_MUTE, '=', False)

    async def select_source(self, source):
        """Select a source from the list of sources."""
        await self.exec_command(CMD_SOURCE, '=', source)

    def available_sources(self):
        """Return a list of available sources."""
        return list(C338_CMDS[CMD_SOURCE]['values'])
