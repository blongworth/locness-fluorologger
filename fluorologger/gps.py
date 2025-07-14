from pynmeagps import NMEAReader
from serial import Serial
import logging

logger = logging.getLogger(__name__)

def read_GPS(port):
    """
    Open serial port, read until NMEA GGA received and parse

    Returns a NMEAReader parsed GGA data object, or None if connection fails
    """
    try:
        with Serial(port, 9600, timeout=1) as stream:
            nmr = NMEAReader(stream)
            parsed_data = None
            while parsed_data is None or parsed_data.msgID != "GGA":
                raw_data, parsed_data = nmr.read()
            return parsed_data
    except Exception as e:
        logger.error(f"Failed to open GPS port {port}: {e}")
        return None
