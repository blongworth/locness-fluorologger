from serial import Serial
from pynmeagps import NMEAReader
with Serial('COM3', 9600, timeout=3) as stream:
    nmr = NMEAReader(stream)
    while True:
        raw_data, parsed_data = nmr.read()
        if parsed_data is not None and parsed_data.msgID == 'GGA':
            print(parsed_data)
            print(f"time: {parsed_data.time} lat: {parsed_data.lat} lon: {parsed_data.lon}")