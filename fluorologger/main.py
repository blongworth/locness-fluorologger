# main program for fluorologger
#
# get current data for fluorometer
# log to file and database

import csv
import logging
import os
import sched
import sqlite3
import sys
import time
from datetime import datetime

from fluorologger.gps import read_GPS
from fluorologger.fluorometer import Fluorometer
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
        conn.execute(f'SELECT 1 FROM {RHO_TABLE} LIMIT 1')
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False

def log_rho(fluorometer, c, conn):
    """
    Continuously get data and store it in the database and file
    """
    # --- Acquire fluorometer data ---
    try:
        avg_voltage = fluorometer.read_voltage()
        concentration = fluorometer.convert_to_concentration(avg_voltage)
    except Exception as e:
        logger.error(f"DAQ hardware error: {e}", exc_info=True)
        avg_voltage = None
        concentration = None
    timestamp = time.time()
    ts = datetime.fromtimestamp(timestamp)

    # --- Acquire GPS data ---
    lat, lon, gps_time = None, None, None
    gps = None
    if GPS_PORT is not None:
        gps = read_GPS(GPS_PORT)
        if gps is not None:
            lat = getattr(gps, 'lat', None)
            lon = getattr(gps, 'lon', None)
            gps_time = getattr(gps, 'time', None)

    # --- Write GPS data to database ---
    if gps is not None:
        try:
            c.execute(
                "INSERT INTO gps (datetime_utc, nmea_time, latitude, longitude) VALUES (?, ?, ?, ?)",
                (timestamp, gps_time, lat, lon)
            )
        except Exception as e:
            logger.error(f"Error writing GPS data: {e}", exc_info=True)

    # --- Write fluorometer data to database and CSV ---
    try:
        logger.info(
            f"Timestamp: {ts}, Gain: {fluorometer.gain}, Voltage: {avg_voltage}, Concentration: {concentration}"
        )
        # Write to CSV file
        data_list = [ts, lat, lon, fluorometer.gain, avg_voltage, concentration]
        log_data(DATAFILE, data_list)
        # Write to rhodamine table only if DAQ succeeded
        if avg_voltage is not None and concentration is not None:
            c.execute(
                f"INSERT INTO {RHO_TABLE} (datetime_utc, gain, voltage, rho_ppb) VALUES (?, ?, ?, ?)",
                (timestamp, fluorometer.gain, avg_voltage, concentration)
            )
    except Exception as e:
        logger.error(f"Error writing rhodamine data: {e}", exc_info=True)
    finally:
        conn.commit()
        if avg_voltage is not None:
            fluorometer.set_autogain(avg_voltage)

def schedule_logging(scheduler, fluorometer, c, conn):
    def run_rho(sched):
        scheduler.enter(READ_TIME, 1, run_rho, (sched,))
        log_rho(fluorometer, c, conn)
    scheduler.enter(READ_TIME, 1, run_rho, (scheduler,))

def main():
    if not ensure_database_ready(DB_PATH):
        print("Database not initialized. Set up with locness-datamanager first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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

    scheduler = sched.scheduler(time.time, time.sleep)

    try:
        schedule_logging(scheduler, fluorometer, c, conn)
        scheduler.run()
    except KeyboardInterrupt:
        fluorometer.close()
        conn.close()
    finally:
        logger.info("Program terminated.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
