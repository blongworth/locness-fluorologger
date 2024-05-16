# main program for fluorologger
#
# get current data for GPS, fluormeter, and TSG
# log to file and database

# TODO: add position and time via NMEA serial stream

import fluorologger.fluorimeter
import fluorologger.gps
import fluorologger.db
import sqlite3
from datetime import datetime
import sched, time


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

    #gps = GPSData()
    # Continuously get data and store it in the database
    def log_rho():
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        print(f"Timestamp: {ts}, Gain: {fluorimeter.gain}, Voltage: {avg_voltage:.2f}, Concentration: {concentration:.2f}")
        write_to_database(timestamp, fluorimeter.gain, avg_voltage, concentration)
        #new_gain = fluorimeter.set_gain(avg_voltage)

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

if __name__ == "__main__":
    main()
