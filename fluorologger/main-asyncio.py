
import asyncio
import serial
from datetime import datetime
from nidaqmx import Task
from nidaqmx.constants import AcquisitionType, LineGrouping
import aiosqlite
import pynmea2

# Parameters
SENSOR_CHANNEL = "Dev1/ai0"
SENSOR_GROUND = "Dev1/ai4"
DIGITAL_OUT_10X = "Dev1/port0/line0"  # Adjust as needed
DIGITAL_OUT_100X = "Dev1/port0/line1"  # Adjust as needed
GPS_PORT = "/dev/ttyUSB0"  # Adjust as needed
GPS_BAUDRATE = 9600
DATABASE = "sensor_data.db"
READINGS_PER_SECOND = 50
AVG_READINGS = 50
CALIBRATION_SLOPE = 1.0  # Replace with your calibration slope
CALIBRATION_INTERCEPT = 0.0  # Replace with your calibration intercept

# Gain levels
GAIN_1X = (False, False)
GAIN_10X = (True, False)
GAIN_100X = (False, True)

class Sensor:
    def __init__(self, channel, ground, rate, avg_readings, digital_out_10x, digital_out_100x):
        self.channel = channel
        self.ground = ground
        self.rate = rate
        self.avg_readings = avg_readings

        # Set up analog input task
        self.ai_task = Task()
        self.ai_task.ai_channels.add_ai_voltage_chan(
            self.channel, terminal_config='DIFF', min_val=0.0, max_val=5.0)
        self.ai_task.timing.cfg_samp_clk_timing(
            rate=self.rate, sample_mode=AcquisitionType.CONTINUOUS)

        # Set up digital output task for gain control
        self.gain_task = Task()
        self.gain_task.do_channels.add_do_chan(
            [digital_out_10x, digital_out_100x], line_grouping=LineGrouping.CHAN_PER_LINE)
        
        self.current_gain = GAIN_1X

    async def read(self):
        readings = []
        for _ in range(self.avg_readings):
            data = self.ai_task.read()
            readings.append(data)
            await asyncio.sleep(1 / self.rate)
        return sum(readings) / len(readings)

    @staticmethod
    def calibrate(raw_value, slope, intercept):
        return raw_value * slope + intercept

    async def set_gain(self, gain):
        if self.current_gain != gain:
            self.gain_task.write(gain, auto_start=True)
            self.current_gain = gain
            return True
        return False

    async def adjust_gain(self, raw_sensor_value):
        if raw_sensor_value < 0.15:
            return await self.set_gain(GAIN_100X)
        elif raw_sensor_value > 2.25:
            return await self.set_gain(GAIN_1X)
        else:
            return await self.set_gain(GAIN_10X)


class GPS:
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.last_latitude = None
        self.last_longitude = None

    async def read(self):
        with serial.Serial(self.port, self.baudrate, timeout=1) as ser:
            while True:
                line = ser.readline().decode('ascii', errors='replace').strip()
                if line.startswith("$GPGGA"):
                    try:
                        msg = pynmea2.parse(line)
                        self.last_latitude = msg.latitude
                        self.last_longitude = msg.longitude
                        return msg
                    except pynmea2.ParseError as e:
                        print(f"Failed to parse GPS data: {e}")
                        continue


class DataLogger:
    def __init__(self, database):
        self.database = database

    async def initialize_db(self):
        async with aiosqlite.connect(self.database) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sensor_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    raw_sensor_value REAL,
                    calibrated_sensor_value REAL,
                    latitude REAL,
                    longitude REAL
                )
            """)
            await db.commit()

    async def log(self, timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude):
        async with aiosqlite.connect(self.database) as db:
            await db.execute("""
                INSERT INTO sensor_data (timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude) 
                VALUES (?, ?, ?, ?, ?)
                """, (timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude))
            await db.commit()


async def main():
    sensor = Sensor(SENSOR_CHANNEL, SENSOR_GROUND, READINGS_PER_SECOND, AVG_READINGS, DIGITAL_OUT_10X, DIGITAL_OUT_100X)
    gps = GPS(GPS_PORT, GPS_BAUDRATE)
    data_logger = DataLogger(DATABASE)

    await data_logger.initialize_db()

    while True:
        raw_sensor_value = await sensor.read()
        calibrated_sensor_value = Sensor.calibrate(raw_sensor_value, CALIBRATION_SLOPE, CALIBRATION_INTERCEPT)
        gps_msg = await gps.read()
        timestamp = datetime.utcnow().isoformat()

        latitude = gps.last_latitude
        longitude = gps.last_longitude

        await data_logger.log(timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude)

        print(f"Logged: {timestamp}, Raw Sensor: {raw_sensor_value}, Calibrated Sensor: {calibrated_sensor_value}, Latitude: {latitude}, Longitude: {longitude}")

        gain_changed = await sensor.adjust_gain(raw_sensor_value)

        if gain_changed:
            print(f"Gain changed. Logging for one more second to allow sensor to settle.")
            for _ in range(READINGS_PER_SECOND):
                raw_sensor_value = await sensor.read()
                calibrated_sensor_value = Sensor.calibrate(raw_sensor_value, CALIBRATION_SLOPE, CALIBRATION_INTERCEPT)
                gps_msg = await gps.read()
                timestamp = datetime.utcnow().isoformat()

                latitude = gps.last_latitude
                longitude = gps.last_longitude

                await data_logger.log(timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude)

                print(f"Logged (settling): {timestamp}, Raw Sensor: {raw_sensor_value}, Calibrated Sensor: {calibrated_sensor_value}, Latitude: {latitude}, Longitude: {longitude}")
                await asyncio.sleep(1 / READINGS_PER_SECOND)

        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
