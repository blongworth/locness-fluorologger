# main program for fluorologger
#
# get current data for GPS, fluormeter, and TSG
# log to file and database

import sqlite3
from datetime import datetime
import sched
import time
import nidaqmx
from nidaqmx.constants import TerminalConfiguration, LineGrouping
from serial import Serial
from pynmeagps import NMEAReader
import os
import csv
import yaml
import logging

# Read the configuration file
with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

# Access configuration values
READ_TIME = config['read_time']
GPS_PORT = config['gps_port']
RHO_SLOPE_1X = config['cal']['slope_1x']
RHO_SLOPE_10X = config['cal']['slope_10x']
RHO_SLOPE_100X = config['cal']['slope_100x']
RHO_OFFSET_1X = config['cal']['offset_1x']
RHO_OFFSET_10X = config['cal']['offset_10x']
RHO_OFFSET_100X = config['cal']['offset_100x']
AUTOGAIN = config['gain']['auto']
GAIN = config['gain']['gain']
LOGFILE = config['file']['log']
DATAFILE = config['file']['data']
DB_PATH = config['file']['db']

# Configure logging
logging.basicConfig(
    # filename=LOGFILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z',
     handlers=[
        logging.FileHandler(LOGFILE),
        logging.StreamHandler()
    ]
)

# Start logger
logger = logging.getLogger(__name__)

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
    
    def log_rho():
        """
        Continuously get data and store it in the database and file
        """
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        gps = read_GPS(GPS_PORT)
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        data_list = [ ts, gps.lat, gps.lon, fluorimeter.gain, avg_voltage, concentration ]
        log_data(DATAFILE, data_list)
        try:
            logger.info(f"Timestamp: {ts}, GPS time: {gps.time}, Lat: {gps.lat:.5f}, Lon: {gps.lon:.5f}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
            c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, gps.lat, gps.lon, fluorimeter.gain, avg_voltage, concentration))
        except (AttributeError, ValueError) as e:
            logger.error(f"GPS data error: {e}")
            logger.info(f"Timestamp: {ts}, GPS time: {None}, Lat: {None}, Lon: {None}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
            c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, None, None, fluorimeter.gain, avg_voltage, concentration))
        except: # Shouldn't have bare except. How to catch all errors and allow program to continue?
            logger.error("Data error, skipping cycle")
        finally:    
            conn.commit()
            fluorimeter.set_autogain(avg_voltage)

    def run_rho(scheduler): 
        """
        Schedule system to take a readings at 1hz
        """
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
        logger.info("Program terminated.")

if __name__ == "__main__":
    main()
