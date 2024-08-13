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
import os
import csv

READ_TIME = 1 # time between fluorometer/GPS readings
GPS_PORT = 'COM10'

# Fluorometer calibration
RHO_SLOPE_1X = 2.30415E-1
RHO_SLOPE_10X = 2.31214E-2
RHO_SLOPE_100X = 2.3824E-3
RHO_OFFSET_1X = -9.21659E-1
RHO_OFFSET_10X = -2.31214E-1
RHO_OFFSET_100X = -1.4532E-1

# Fluorometer gain
AUTOGAIN = True
GAIN = 1

# Output files
LOGFILE = 'C:/Users/CSL 2/Documents/LOCNESS_data/fluorometer_data.csv'  # Name of the CSV file
DB_PATH = 'C:/Users/CSL 2/Documents/LOCNESS_data/data.db' # Path to SQLite DB

def read_GPS(port):
    '''
    Open serial port, read until NMEA GGA received and parse

    Returns a NMEAReader parsed GGA data object
    '''
    with Serial(port, 9600, timeout=1) as stream:
        nmr = NMEAReader(stream)
        parsed_data = None
        while parsed_data is None or parsed_data.msgID != 'GGA':
            raw_data, parsed_data = nmr.read()
        return parsed_data
        
class Fluorimeter:
    '''Fluorometer class. Handles fluorometer DAQ and data processing'''
    def __init__(self, slope_1x, slope_10x, slope_100x, offset_1x, offset_10x, offset_100x, autogain = True, gain = 1):
        self.slope_1x = slope_1x
        self.slope_10x = slope_10x
        self.slope_100x = slope_100x
        self.offset_1x = offset_1x
        self.offset_10x = offset_10x
        self.offset_100x = offset_100x
        self.autogain = autogain
        self.gain_change_delay = 3 # seconds to delay reading after gain change
        self.last_gain_change = time.time()
        self.gain = gain

        # Connect to the DAQ device
        self.task = nidaqmx.Task()
        self.task.ai_channels.add_ai_voltage_chan("fluor/ai0",
                                                  terminal_config=TerminalConfiguration.DIFF)
        # Configure the timing
        self.task.timing.cfg_samp_clk_timing(rate=1000, samps_per_chan=100)
        
        # Add digital output channels
        self.do_task = nidaqmx.Task()
        self.do_task.do_channels.add_do_chan("fluor/port0/line0:1",
                                             line_grouping=LineGrouping.CHAN_PER_LINE)
        
        # Start the tasks
        self.do_task.start()

        # Initial gain setting
        self.set_gain(self.gain)

    def read_voltage(self):
        '''
        Run a task that reads 100 voltage samples at 1kHz
        
        Returns average voltage
        '''
        self.task.start()
        voltages = []
        # Read the data
        voltages = self.task.read(number_of_samples_per_channel=100)
        self.task.stop()
        avg_voltage = sum(voltages) / len(voltages)
        return avg_voltage

    def convert_to_concentration(self, voltage):
        if self.gain == 1:
            concentration = self.slope_1x * voltage * 1000 + self.offset_1x
        elif self.gain == 10:
            concentration = self.slope_10x * voltage * 1000 + self.offset_10x
        elif self.gain == 100:
            concentration = self.slope_100x * voltage * 1000 + self.offset_100x
            
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

    def set_gain(self, gain):
        if gain == 1:
            self.do_task.write([True, True])
        if gain == 10:
            self.do_task.write([False, True])
        if gain == 100:
            self.do_task.write([True, False])

    def set_autogain(self, avg_voltage):
        new_gain = self.determine_gain(avg_voltage)
        current_time = time.time()
        if new_gain != self.gain:
            self.gain = new_gain
            self.last_gain_change = current_time
            self.set_gain(self.gain)
            time.sleep(self.gain_change_delay)
    
def log_data(filename, data):
    file_exists = os.path.isfile(filename)
    
    with open(filename, 'a', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        
        if not file_exists:
            # Write header if file doesn't exist
            csvwriter.writerow(['timestamp', 'latitude', 'longitude', 'gain', 'voltage', 'concentration'])
        
        csvwriter.writerow(data)

def main():

    # Connect to the SQLite database 
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create a table to store the data
    # or append if it already exists
    c.execute('''CREATE TABLE IF NOT EXISTS data
              (timestamp INTEGER, latitude REAL, longitude REAL, gain INTEGER, voltage REAL, concentration REAL)''')

    fluorimeter = Fluorimeter(RHO_SLOPE_1X,
                              RHO_SLOPE_10X,
                              RHO_SLOPE_100X, 
                              RHO_OFFSET_1X, 
                              RHO_OFFSET_10X,
                              RHO_OFFSET_100X, 
                              autogain=AUTOGAIN, 
                              gain=GAIN)
    
    # Continuously get data and store it in the database
    def log_rho():
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        gps = read_GPS(GPS_PORT)
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        data_list = [ ts, gps.lat, gps.lon, fluorimeter.gain, avg_voltage, concentration ]
        log_data(LOGFILE, data_list)
        try:
            print(f"Timestamp: {ts}, GPS time: {gps.time}, Lat: {gps.lat:.5f}, Lon: {gps.lon:.5f}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
            c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, gps.lat, gps.lon, fluorimeter.gain, avg_voltage, concentration))
        except (AttributeError, ValueError) as e:
            print("GPS data error")
            print(f"Timestamp: {ts}, GPS time: {None}, Lat: {None}, Lon: {None}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
            c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, None, None, fluorimeter.gain, avg_voltage, concentration))
        except:
            print("Data error, skipping cycle")
        finally:    
            conn.commit()
            fluorimeter.set_autogain(avg_voltage)

    # schedule system to take a readings at 1hz
    def run_rho(scheduler): 
        # schedule the next call first
        scheduler.enter(1, 1, run_rho, (scheduler,))
        log_rho()

    try:
        my_scheduler = sched.scheduler(time.time, time.sleep)
        my_scheduler.enter(READ_TIME, 1, run_rho, (my_scheduler,))
        my_scheduler.run()

    except KeyboardInterrupt: 
        # Clean up daq tasks
        fluorimeter.task.close()
        fluorimeter.do_task.stop()
        fluorimeter.do_task.close()

        # Close the DB
        conn.close()

    finally:
        print("Program terminated.")

if __name__ == "__main__":
    main()
