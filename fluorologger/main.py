# main program for fluorologger
#
# get current data for GPS, fluormeter, and TSG
# log to file and database

# TODO: add position and time via NMEA serial stream

import sqlite3
from datetime import datetime
import sched, time
import nidaqmx
from nidaqmx.constants import AcquisitionType, TerminalConfiguration, LineGrouping
import time
from serial import Serial
from pynmeagps import NMEAReader


# need error handling
def read_GPS(gps):
    raw_data, parsed_data = gps.read()
    if parsed_data is not None and parsed_data.msgID == 'GGA':
        time = parsed_data.time
        lat = parsed_data.lat
        lon = parsed_data.lon
        return time, lat, lon
        

# TODO: read voltage as HW timed burst

class Fluorimeter:
    def __init__(self, slope, offset):
        self.slope = slope
        self.offset = offset
        self.gain_change_delay = 3 # seconds to delay reading after gain change
        self.last_gain_change = time.time()
        self.gain = 1

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
        concentration = self.slope * voltage / self.gain + self.offset
        return concentration

    def determine_gain(self, avg_voltage):
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
    # Linear correction parameters
    slope = 0.5  # Slope of the linear correction
    offset = 0.2  # Offset of the linear correction

    # Connect to the SQLite database
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    # Create a table to store the data
    # or append if it already exists
    c.execute('''CREATE TABLE IF NOT EXISTS data
              (timestamp INTEGER, gain INTEGER, voltage REAL, concentration REAL)''')

    fluorimeter = Fluorimeter(slope, offset)
    ser = Serial('COM3', 9600, timeout = 1)
    gps = NMEAReader(ser)

    # Continuously get data and store it in the database
    def log_rho():
        gps_time, lat, lon = read_GPS(gps)
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        print(f"Timestamp: {ts}, GPS time: {gps_time}, Lat: {lat}, Lon: {lon}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.2f}, Concentration: {concentration:.2f}")
        c.execute("INSERT INTO data VALUES (?, ?, ?, ?)", (timestamp, fluorimeter.gain, avg_voltage, concentration))
        conn.commit()
        new_gain = fluorimeter.set_gain(avg_voltage)

    def run_rho(scheduler): 
        # schedule the next call first
        scheduler.enter(1, 1, run_rho, (scheduler,))
        log_rho()

    my_scheduler = sched.scheduler(time.time, time.sleep)
    my_scheduler.enter(1, 1, run_rho, (my_scheduler,))
    my_scheduler.run()
        
    # Clean up
    task.close()
    conn.close()
    ser.close()

if __name__ == "__main__":
    main()
