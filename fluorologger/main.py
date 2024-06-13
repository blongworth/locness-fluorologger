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
RHO_STD_V = .00539
RHO_STD_C = 1
RHO_ZERO_V_1X = -0.0079
RHO_ZERO_V_10X = -0.0011
RHO_ZERO_V_100X = 0.0690
AUTOGAIN = True
GAIN = 1

# need error handling and handle no fix
def read_GPS(port):
    try:
        with Serial(port, 9600, timeout=1) as stream:
            nmr = NMEAReader(stream)
            parsed_data = None
            while parsed_data is None or parsed_data.msgID != 'GGA':
                raw_data, parsed_data = nmr.read()
            return parsed_data
    except:
        print("GPS Error")
        
# def read_GPS(gps):
#     raw_data, parsed_data = gps.read()
#     if parsed_data is not None and parsed_data.msgID == 'GGA':
#         time = parsed_data.time
#         lat = parsed_data.lat
#         lon = parsed_data.lon
#         return time, lat, lon
        

# TODO: read voltage as HW timed burst

class Fluorimeter:
    def __init__(self, std_v, std_c, zero_1x, zero_10x, zero_100x, autogain = True, gain = 1):
        self.std_v = std_v
        self.std_c = std_c
        self.zero_1x = zero_1x
        self.zero_10x = zero_10x
        self.zero_100x = zero_100x
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
        
        
        # Add digital output channels - needs to be separate task
        self.do_task = nidaqmx.Task()
        self.do_task.do_channels.add_do_chan("fluor/port0/line0:1",
                                             line_grouping=LineGrouping.CHAN_PER_LINE)
        
        # Start the tasks
        self.do_task.start()

        # Initial gain setting
        self.set_gain(self.gain)

    def read_voltage(self):
        self.task.start()
        voltages = []
        # Read the data
        voltages = self.task.read(number_of_samples_per_channel=100)
        self.task.stop()
        avg_voltage = sum(voltages) / len(voltages)
        return avg_voltage

    def convert_to_concentration(self, voltage):
        if self.gain == 1:
            zero = self.zero_1x
        elif self.gain == 10:
            zero = self.zero_10x
        elif self.gain == 100:
            zero = self.zero_100x
            
        concentration = (self.std_c / (self.std_v - zero)) * (voltage / self.gain - zero)
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
    
def main():

    # Connect to the SQLite database
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    # Create a table to store the data
    # or append if it already exists
    c.execute('''CREATE TABLE IF NOT EXISTS data
              (timestamp INTEGER, latitude REAL, longitude REAL, gain INTEGER, voltage REAL, concentration REAL)''')

    fluorimeter = Fluorimeter(RHO_STD_V,
                              RHO_STD_C, 
                              RHO_ZERO_V_1X, 
                              RHO_ZERO_V_10X, 
                              RHO_ZERO_V_100X, 
                              autogain=AUTOGAIN, 
                              gain=GAIN)
    
    #ser = Serial('COM3', 9600, timeout = 1)
    #gps = NMEAReader(ser)

    # Continuously get data and store it in the database
    def log_rho():
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        gps = read_GPS(GPS_PORT)
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        try:
            print(f"Timestamp: {ts}, GPS time: {gps.time}, Lat: {gps.lat:.5f}, Lon: {gps.lon:.5f}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
            c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, gps.lat, gps.lon, fluorimeter.gain, avg_voltage, concentration))
        except ValueError:
            print("GPS data error")
            print(gps.time)
            print(gps.lat)
            print(gps.lon)
            print(f"Timestamp: {ts}, GPS time: {gps.time}, Lat: {None}, Lon: {None}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}")
            c.execute("INSERT INTO data VALUES (?, ?, ?, ?, ?, ?)", (timestamp, None, None, fluorimeter.gain, avg_voltage, concentration))
        finally:    
            conn.commit()
            fluorimeter.set_autogain(avg_voltage)

    def run_rho(scheduler): 
        # schedule the next call first
        scheduler.enter(1, 1, run_rho, (scheduler,))
        log_rho()

    try:
        my_scheduler = sched.scheduler(time.time, time.sleep)
        my_scheduler.enter(1, 1, run_rho, (my_scheduler,))
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
