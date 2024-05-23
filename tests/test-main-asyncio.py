
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, time
import asyncio

# Import the classes from your script
from fluorologger import Sensor, GPS, DataLogger, GAIN_1X, GAIN_10X, GAIN_100X


class TestSensor(unittest.TestCase):
    def setUp(self):
        self.sensor = Sensor("Dev1/ai0", "Dev1/ai4", 50, 50, "Dev1/port0/line0", "Dev1/port0/line1")
        self.sensor.ai_task = MagicMock()
        self.sensor.gain_task = MagicMock()

    @patch('asyncio.sleep', return_value=None)
    def test_read(self, _):
        self.sensor.ai_task.read = MagicMock(side_effect=[1, 2, 3, 4, 5])
        result = asyncio.run(self.sensor.read())
        self.assertEqual(result, 3)  # Average of 1, 2, 3, 4, 5

    def test_calibrate(self):
        raw_value = 2.0
        slope = 2.0
        intercept = 1.0
        result = Sensor.calibrate(raw_value, slope, intercept)
        self.assertEqual(result, 5.0)  # 2 * 2 + 1

    @patch('asyncio.sleep', return_value=None)
    def test_set_gain(self, _):
        asyncio.run(self.sensor.set_gain(GAIN_10X))
        self.sensor.gain_task.write.assert_called_with(GAIN_10X, auto_start=True)
        self.assertEqual(self.sensor.current_gain, GAIN_10X)

    @patch('asyncio.sleep', return_value=None)
    def test_adjust_gain(self, _):
        # Test setting gain to 100X
        result = asyncio.run(self.sensor.adjust_gain(0.1))
        self.assertTrue(result)
        self.sensor.gain_task.write.assert_called_with(GAIN_100X, auto_start=True)

        # Test setting gain to 1X
        result = asyncio.run(self.sensor.adjust_gain(2.5))
        self.assertTrue(result)
        self.sensor.gain_task.write.assert_called_with(GAIN_1X, auto_start=True)

        # Test setting gain to 10X
        result = asyncio.run(self.sensor.adjust_gain(1.0))
        self.assertTrue(result)
        self.sensor.gain_task.write.assert_called_with(GAIN_10X, auto_start=True)


class TestGPS(unittest.TestCase):
    def setUp(self):
        self.gps = GPS("/dev/ttyUSB0", 9600)
        self.gps_serial = MagicMock()

    @patch('serial.Serial', return_value=MagicMock())
    def test_read(self, mock_serial):
        mock_serial_instance = mock_serial.return_value.__enter__.return_value
        mock_serial_instance.readline.return_value = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
        result = asyncio.run(self.gps.read())
        self.assertEqual(self.gps.last_latitude, 48.1173)
        self.assertEqual(self.gps.last_longitude, 11.516666666666667)
        self.assertEqual(self.gps.last_time, time(12, 35, 19))

    def test_get_timestamp(self):
        self.gps.last_time = time(12, 35, 19)
        now = datetime.utcnow()
        expected_timestamp = datetime.combine(now.date(), self.gps.last_time).isoformat()
        if datetime.combine(now.date(), self.gps.last_time) > now:
            expected_timestamp = datetime.combine(now.date().replace(day=now.day - 1), self.gps.last_time).isoformat()
        self.assertEqual(self.gps.get_timestamp(), expected_timestamp)

        # Test with no GPS time
        self.gps.last_time = None
        self.assertIsNotNone(self.gps.get_timestamp())


class TestDataLogger(unittest.TestCase):
    def setUp(self):
        self.logger = DataLogger("test_db.db")
        self.logger.initialize_db = AsyncMock()
        self.logger.log = AsyncMock()

    @patch('aiosqlite.connect', new_callable=AsyncMock)
    def test_initialize_db(self, mock_connect):
        asyncio.run(self.logger.initialize_db())
        mock_connect.return_value.execute.assert_called_once()
        mock_connect.return_value.commit.assert_called_once()

    @patch('aiosqlite.connect', new_callable=AsyncMock)
    def test_log(self, mock_connect):
        timestamp = "2023-01-01T12:00:00Z"
        raw_sensor_value = 1.23
        calibrated_sensor_value = 2.34
        latitude = 48.1173
        longitude = 11.5167
        asyncio.run(self.logger.log(timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude))
        mock_connect.return_value.execute.assert_called_once_with(
            "INSERT INTO sensor_data (timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude) VALUES (?, ?, ?, ?, ?)",
            (timestamp, raw_sensor_value, calibrated_sensor_value, latitude, longitude)
        )
        mock_connect.return_value.commit.assert_called_once()

if __name__ == "__main__":
    unittest.main()
