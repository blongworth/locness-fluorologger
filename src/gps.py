import asyncio
import pynmea2
import serial
from datetime import datetime

# Define a class to manage current position and time
class GPSData:
    def __init__(self):
        self.latitude = None
        self.longitude = None
        self.time = None

    def update_data(self, nmea_sentence):
        if isinstance(nmea_sentence, pynmea2.GGA):
            latitude = nmea_sentence.latitude
            longitude = nmea_sentence.longitude
            time = nmea_sentence.timestamp.strftime("%H:%M:%S")
            if (latitude != self.latitude or longitude != self.longitude or time != self.time):
                self.latitude = latitude
                self.longitude = longitude
                self.time = time
                return True
        return False

# Open a file to write the output
output_file = open("gps_data.txt", "a")  # "a" for append mode

# Define a function to print and write data
def print_and_write_data(gps_data):
    if gps_data.latitude is not None and gps_data.longitude is not None and gps_data.time is not None:
        print(f"Time = {gps_data.time}, Latitude = {gps_data.latitude}, Longitude = {gps_data.longitude}")
        output_file.write(f"{datetime.now().isoformat()}, {gps_data.time}, {gps_data.latitude}, {gps_data.longitude}\n")
        output_file.flush()  # Flush the buffer to ensure data is written immediately

# Define an asyncio protocol to handle UDP communication
class UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, gps_data, packet_queue):
        super().__init__()
        self.gps_data = gps_data
        self.packet_queue = packet_queue

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        received_data = data.decode("ascii")
        self.packet_queue.put_nowait(received_data)  # Put the received packet into the queue

    def error_received(self, exc):
        print('Error received:', exc)

    def connection_lost(self, exc):
        print('Closing transport')
        self.transport.close()

async def process_packets(gps_data, packet_queue):
    while True:
        received_data = await packet_queue.get()  # Wait until a packet is available in the queue
        # Parse NMEA sentence
        try:
            nmea_sentence = pynmea2.parse(received_data)
            if gps_data.update_data(nmea_sentence):  # Update GPS data only if new
                print_and_write_data(gps_data)  # Print and write data
        except pynmea2.ParseError:
            print(f"Failed to parse NMEA sentence: {received_data}")

async def main(gps_source = 'serial'):
    # Create an event loop
    loop = asyncio.get_running_loop()

    # Create a GPSData instance
    gps_data = GPSData()

    # Create a packet queue
    packet_queue = asyncio.Queue()

    if gps_source == 'udp':
        # Define the IP address and port of the server
        SERVER_IP = "192.168.1.32"
        #SERVER_PORT = 16001 #new GPS, misses packets
        SERVER_PORT = 16002

        # Create a UDP endpoint and start the UDP protocol
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(gps_data, packet_queue),
            local_addr=("0.0.0.0", SERVER_PORT)
        )

        print(f"Listening for data on {SERVER_IP}:{SERVER_PORT}")

    elif gps_source == 'serial':
        # Open the serial port for GPS data
        
        serial_port = "/dev/cu.usbserial-FT1Z1JAF"
        baud = 4800
        with serial.Serial(serial_port, baud, timeout=1) as ser:
            while True:
                try:
                    line = ser.readline().decode("ascii").strip()
                    if line.startswith("$GP"):
                        packet_queue.put_nowait(line)
                    else:
                        print(f"Ignoring non-NMEA data: {line}")
                except UnicodeDecodeError:
                    print("Error decoding serial data. Skipping...")
                    continue
    else:
        raise ValueError('gps_source should be "udp" or "serial"')
    return

    # Start the task to process packets
    await process_packets(gps_data, packet_queue)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        # Close the file when done
        output_file.close()
