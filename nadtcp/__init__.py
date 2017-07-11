import asyncio
import logging
from functools import partial

_LOGGER = logging.getLogger(__name__)


class NADC338Protocol(asyncio.Protocol):
    MSG_MODEL = 'NADC338'

    MSG_ON = 'On'
    MSG_OFF = 'Off'

    SUPPORTED_COMMANDS = {
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
             'values': range(-70, -19),
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
             'values': [MSG_MODEL]
             }
    }

    MSG_MAIN = "Main"
    MSG_BRIGHTNESS = "Main.Brightness"
    MSG_BASS_EQ = "Main.Bass"
    MSG_CONTROL_STANDBY = "Main.ControlStandby"
    MSG_AUTO_STANDBY = "Main.AutoStandby"
    MSG_VERSION = "Main.Version"
    MSG_MUTE = "Main.Mute"
    MSG_POWER = "Main.Power"
    MSG_AUTO_SENSE = "Main.AutoSense"
    MSG_SOURCE = "Main.Source"
    MSG_VOLUME = "Main.Volume"

    PORT = 30001

    transport = None  # type: asyncio.Transport

    def __init__(self, loop=None, message_received=None, disconnect_callback=None) -> None:
        if loop:
            self.loop = loop
        else:
            self.loop = asyncio.get_event_loop()
        self.packet = ''
        self.buffer = ''
        self.message_received = message_received
        self.disconnect_callback = disconnect_callback

        self.supported_commands = self.SUPPORTED_COMMANDS.copy()

    def connection_made(self, transport):
        self.transport = transport
        _LOGGER.debug('connected')

    def data_received(self, data):
        data = data.decode('utf-8')
        self.buffer += data.replace('\x00', '')
        self.handle_lines()

    def handle_lines(self):
        while "\r\n" in self.buffer:
            line, self.buffer = self.buffer.split("\r\n", 1)
            self.handle_line(line)

    def handle_line(self, line):
        _LOGGER.debug('received data: %s', line)

        key, value = line.split("=")

        if 'type' in self.supported_commands[key]:
            value = self.supported_commands[key]['type'](value)

        if self.message_received:
            self.message_received(key, value)

    def handle_raw_packet(self, raw_packet: bytes) -> None:
        raise NotImplementedError()

    def send_raw_packet(self, packet: str):
        data = packet + '\r\n'
        _LOGGER.debug('writing data: %s', repr(data))
        self.transport.write(data.encode('utf-8'))

    def connection_lost(self, exc):
        if exc:
            _LOGGER.error(exc, exc_info=True)
        else:
            _LOGGER.info('disconnected because of close/abort.')
        if self.disconnect_callback:
            self.disconnect_callback(exc)

    def send_command(self, command, operator, value=None):
        cmd_desc = self.supported_commands[command]
        if operator in cmd_desc['supported_operators']:
            if operator is '=' and value is None:
                raise ValueError('No value provided')
            elif operator in ['?', '-', '+'] and value is not None:
                raise ValueError('Operator \'%s\' cannot be called with a value' % operator)

            if value is None:
                cmd = command + operator
            else:
                if 'values' in cmd_desc and value not in cmd_desc['values']:
                    raise ValueError('Given value \'%s\' is not one of %s' % (value, cmd_desc['values']))

                cmd = command + operator + str(value)
        else:
            raise ValueError('Invalid operator provided %s' % operator)

        self.send_raw_packet(cmd)

    def get_value(self, command):
        return self.send_command(command, '?')

    def set_value(self, command, value):
        return self.send_command(command, '=', value)

    def cycle_up(self, command):
        return self.send_command(command, '+')

    def cycle_down(self, command):
        return self.send_command(command, '-')

    def get_available_sources(self):
        return list(self.supported_commands[self.MSG_SOURCE]['values'])

    @staticmethod
    def create_nad_connection(loop, target_ip, disconnect_callback=None, message_received_callback=None):
        _LOGGER.debug('Initializing nad connection to %s', target_ip)

        protocol = partial(
            NADC338Protocol,
            loop=loop,
            disconnect_callback=disconnect_callback,
            message_received=message_received_callback
        )

        return loop.create_connection(protocol, target_ip, NADC338Protocol.PORT)
