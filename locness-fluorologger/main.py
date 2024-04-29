# main program for fluorologger
#
# get current data for GPS, fluormeter, and TSG
# log to file and database

# TODO: add position and time via NMEA serial stream

import fluorimeter
import gps
import db

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

    gps = GPSData()

    # Continuously get data and store it in the database
    while True:
        avg_voltage = fluorimeter.read_voltage()
        concentration = fluorimeter.convert_to_concentration(avg_voltage)
        timestamp = time.time()
        print(f"Timestamp: {timestamp}, Gain: {self.gain}, Voltage: {avg_voltage:.2f}, Concentration: {concentration:.2f}")

        write_to_database(timestamp, self.gain, avg_voltage, concentration)
        new_gain = fluorimeter.adjust_gain(avg_voltage)

    # Clean up
    task.close()
    conn.close()

if __name__ == "__main__":
    main()
