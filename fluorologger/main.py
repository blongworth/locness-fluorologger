# main program for fluorologger
#
# get current data for GPS, fluormeter, and TSG
# log to file and database

import sqlite3
from datetime import datetime
import sched, time
import nidaqmx
from nidaqmx.constants import AcquisitionType, TerminalConfiguration, LineGrouping
import time
from serial import Serial
from pynmeagps import NMEAReader

GPS_PORT = 'COM3'
RHO_SLOPE = 81.47
RHO_OFFSET_1X = 0.005
RHO_OFFSET_10X = 0
RHO_OFFSET_100X = 0

# need error handling and handle no fix
def read_GPS(port):
    with Serial(port, 9600, timeout=1) as stream:
        nmr = NMEAReader(stream)
        parsed_data = None
        while parsed_data is None or parsed_data.msgID != 'GGA':
            raw_data, parsed_data = nmr.read()
        #print(parsed_data)
        return parsed_data
        #print(f"time: {parsed_data.time} lat: {parsed_data.lat:.5f} lon: {parsed_data.lon:.5f}")

# def read_GPS(gps):
#     raw_data, parsed_data = gps.read()
#     if parsed_data is not None and parsed_data.msgID == 'GGA':
#         time = parsed_data.time
#         lat = parsed_data.lat
#         lon = parsed_data.lon
#         return time, lat, lon
        

# TODO: read voltage as HW timed burst

class Fluorimeter:
    def __init__(self, slope, offset_1x, offset_10x, offset_100x, autogain = True, gain = 1):
        self.slope = slope
        self.offset_1x = offset_1x
        self.offset_10x = offset_10x
        self.offset_100x = offset_100x
        self.autogain = autogain
        self.gain_change_delay = 3 # seconds to delay reading after gain change
        self.last_gain_change = time.time()
        self.gain = gain

        # Connect to the DAQ device
        self.task = nidaqmx.Task()
        self.task.ai_channels.add_ai_voltage_chan("fluor/ai0", terminal_config=TerminalConfiguration.DIFF)
        
        # Add digital output channels to the task - needs to be separate task
        self.do_task = nidaqmx.Task()
        self.do_task.do_channels.add_do_chan("fluor/port0/line0:1", line_grouping=LineGrouping.CHAN_PER_LINE)

    def read_voltage(self):
        voltages = []
        start_time = time.time()
        for i in range(50):
            voltage = self.task.read()
            voltages.append(voltage)
            time.sleep(0.01)  # 50 readings per 0.5 second

        avg_voltage = sum(voltages) / len(voltages)
        return avg_voltage

    def convert_to_concentration(self, voltage):
        if self.gain == 1:
            offset = self.offset_1x
        elif self.gain == 10:
            offset = self.offset_10x
        elif self.gain == 100:
            offset = self.offset_100x
            
        concentration = self.slope * voltage / self.gain + offset
        return concentration

    def determine_gain(self, avg_voltage):
           # if autogain disabled, use gain set at initialization
            if not self.autogain:
                return self.gain
            current_time = time.time()
            new_gain = self.gain
            if current_time - self.last_gain_change >= self.gain_change_delay:
                if avg_voltage < 0.15:
                    if self.gain == 1:
                        new_gain = 10
                    else:
                        new_gain = 100
                elif avg_voltage > 2.25:
                    if self.gain == 100:
                        new_gain = 10
                    else:
                        new_gain = 1
            return new_gain

    def set_gain(self, avg_voltage):
        new_gain = self.determine_gain(avg_voltage)
        current_time = time.time()
        if new_gain != self.gain:
            self.gain = new_gain
            self.last_gain_change = current_time
            if self.gain == 1:
                self.do_task.write([False, False])
            if self.gain == 10:
                self.do_task.write([True, False])
            if self.gain == 100:
                self.do_task.write([False, True])
            time.sleep(self.gain_change_delay)
    
def main():

    # Connect to the SQLite database
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    # Create a table to store the data
    # or append if it already exists
    c.execute('''CREATE TABLE IF NOT EXISTS data
              (timestamp INTEGER, latitude REAL, longitude REAL, gain INTEGER, voltage REAL, concentration REAL)''')

    fluorimeter = Fluorimeter(RHO_SLOPE, 
                              RHO_OFFSET_1X, 
                              RHO_OFFSET_10X, 
                              RHO_OFFSET_100X, 
                              autogain=False, gain=100)
    
    #ser = Serial('COM3', 9600, timeout = 1)
    #gps = NMEAReader(ser)

    # Continuously get data and store it in the database
    def log_rho():
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        gps = read_GPS(GPS_PORT)
        if gps is None:
            gps.time = None
            gps.lat = None
            gps.lon = None
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        print(f"Timestamp: {ts}, GPS time: {gps.time}, Lat: {gps.lat:.5f}, Lon: {gps.lon:.5f}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
        c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, gps.lat, gps.lon, fluorimeter.gain, avg_voltage, concentration))
        conn.commit()
        new_gain = fluorimeter.set_gain(avg_voltage)

    def run_rho(scheduler): 
        # schedule the next call first
        scheduler.enter(1, 1, run_rho, (scheduler,))
        log_rho()

    try:
        my_scheduler = sched.scheduler(time.time, time.sleep)
        my_scheduler.enter(1, 1, run_rho, (my_scheduler,))
        my_scheduler.run()

    except KeyboardInterrupt: 
        # Clean up
        fluorimeter.task.close()
        fluorimeter.do_task.close()
        conn.close()

    finally:
        print("Program terminated.")
    

if __name__ == "__main__":
    main()
