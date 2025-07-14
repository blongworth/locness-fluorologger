# main program for fluorologger
#
# get current data for GPS, fluormeter, and TSG
# log to file and database

import csv
import logging
import os
import sched
import sqlite3
import sys
import time
from datetime import datetime

import nidaqmx
from nidaqmx.constants import TerminalConfiguration, LineGrouping
from fluorologger.gps import read_GPS
import yaml

# Read the configuration file
with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

# Access configuration values
READ_TIME = config["read_time"]
GPS_PORT = config.get("gps_port", None)  # Use None if not defined
RHO_SLOPE_1X = config["cal"]["slope_1x"]
RHO_SLOPE_10X = config["cal"]["slope_10x"]
RHO_SLOPE_100X = config["cal"]["slope_100x"]
RHO_OFFSET_1X = config["cal"]["offset_1x"]
RHO_OFFSET_10X = config["cal"]["offset_10x"]
RHO_OFFSET_100X = config["cal"]["offset_100x"]
AUTOGAIN = config["gain"]["auto"]
GAIN = config["gain"]["gain"]
LOGFILE = config["file"]["log"]
DATAFILE = config["file"]["data"]
DB_PATH = config["db"]["filename"]
RHO_TABLE = config["db"]["table"]

# Configure logging
logging.basicConfig(
    # filename=LOGFILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    handlers=[logging.FileHandler(LOGFILE), logging.StreamHandler()],
)


# Start logger
logger = logging.getLogger(__name__)


class Fluorometer:
    """Fluorometer class. Handles fluorometer DAQ and data processing"""

    def __init__(
        self,
        slope_1x,
        slope_10x,
        slope_100x,
        offset_1x,
        offset_10x,
        offset_100x,
        autogain=True,
        gain=1,
    ):
        self.slope_1x = slope_1x
        self.slope_10x = slope_10x
        self.slope_100x = slope_100x
        self.offset_1x = offset_1x
        self.offset_10x = offset_10x
        self.offset_100x = offset_100x
        self.autogain = autogain
        self.gain_change_delay = 3  # seconds to delay reading after gain change
        self.last_gain_change = time.time()
        self.gain = gain

        # Connect to the DAQ device
        self.task = nidaqmx.Task()
        self.task.ai_channels.add_ai_voltage_chan(
            "fluor/ai0", terminal_config=TerminalConfiguration.DIFF
        )
        # Configure the timing
        self.task.timing.cfg_samp_clk_timing(rate=1000, samps_per_chan=100)

        # Add digital output channels
        self.do_task = nidaqmx.Task()
        self.do_task.do_channels.add_do_chan(
            "fluor/port0/line0:1", line_grouping=LineGrouping.CHAN_PER_LINE
        )

        # Start the tasks
        self.do_task.start()

        # Initial gain setting
        self.set_gain(self.gain)

    def read_voltage(self):
        """
        Run a task that reads 100 voltage samples at 1kHz

        Returns average voltage
        """
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

    with open(filename, "a", newline="") as csvfile:
        csvwriter = csv.writer(csvfile)

        if not file_exists:
            # Write header if file doesn't exist
            csvwriter.writerow(
                [
                    "timestamp",
                    "latitude",
                    "longitude",
                    "gain",
                    "voltage",
                    "concentration",
                ]
            )

        csvwriter.writerow(data)

def ensure_database_ready(db_path):
    """Quick check that database is properly initialized"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f'SELECT 1 FROM {DB_TABLE} LIMIT 1')
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False

def main():
    # Connect to the SQLite database
    if not ensure_database_ready(DB_PATH):
        print("Database not initialized. Set up with locness-datamanager first.")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Log GPS status
    if GPS_PORT is not None:
        logger.info(f"GPS enabled on port {GPS_PORT}")
    else:
        logger.info("GPS disabled - no GPS port configured")

    fluorometer = Fluorometer(
        RHO_SLOPE_1X,
        RHO_SLOPE_10X,
        RHO_SLOPE_100X,
        RHO_OFFSET_1X,
        RHO_OFFSET_10X,
        RHO_OFFSET_100X,
        autogain=AUTOGAIN,
        gain=GAIN,
    )

    def log_rho():
        """
        Continuously get data and store it in the database and file
        """
        avg_voltage = fluorometer.read_voltage()
        concentration = fluorometer.convert_to_concentration(avg_voltage)
        
        # Only acquire GPS data if GPS_PORT is defined
        if GPS_PORT is not None:
            gps = read_GPS(GPS_PORT)
        else:
            gps = None
            
        timestamp = time.time()
        ts = datetime.fromtimestamp(timestamp)
        if gps is not None:
            lat = gps.lat
            lon = gps.lon
            gps_time = getattr(gps, 'time', None)
            # Write GPS data to 'gps' table
            try:
                c.execute(
                    "INSERT INTO gps (datetime_utc, nmea_time, latitude, longitude) VALUES (?, ?, ?, ?)",
                    (timestamp, gps_time, lat, lon)
                )
            except Exception as e:
                logger.error(f"Error writing GPS data: {e}", exc_info=True)
        else:
            lat = None
            lon = None
            gps_time = None

        # Write fluorometer data
        try:
            logger.info(
                f"Timestamp: {ts}, Gain: {fluorometer.gain}, Voltage: {avg_voltage:.3f}, Concentration: {concentration:.3f}"
            )
            data_list = [ts, lat, lon, fluorometer.gain, avg_voltage, concentration]
            log_data(DATAFILE, data_list)
            c.execute(
                f"INSERT INTO {RHO_TABLE} (datetime_utc, gain, voltage, rho_ppb) VALUES (?, ?, ?, ?)",
                (timestamp, fluorometer.gain, avg_voltage, concentration)
            )
        except Exception as e:
            logger.error(f"Error writing rhodamine data: {e}", exc_info=True)
        finally:
            conn.commit()
            fluorometer.set_autogain(avg_voltage)

    def run_rho(scheduler):
        """
        Schedule system to take a readings every READ_TIME seconds
        """
        scheduler.enter(READ_TIME, 1, run_rho, (scheduler,))
        log_rho()

    try:
        my_scheduler = sched.scheduler(time.time, time.sleep)
        my_scheduler.enter(READ_TIME, 1, run_rho, (my_scheduler,))
        my_scheduler.run()

    except KeyboardInterrupt:
        # Clean up daq tasks
        fluorometer.task.close()
        fluorometer.do_task.stop()
        fluorometer.do_task.close()

        # Close the DB
        conn.close()

    finally:
        logger.info("Program terminated.")


if __name__ == "__main__":
    main()
