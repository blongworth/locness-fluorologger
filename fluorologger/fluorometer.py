import nidaqmx
from nidaqmx.constants import TerminalConfiguration, LineGrouping
import time
import logging

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
        std_concentration,
        std_voltage_10x,
        blank_1x,
        blank_10x,
        blank_100x,
        autogain=True,
        gain=1,
    ):
        self.slope_1x = slope_1x
        self.slope_10x = slope_10x
        self.slope_100x = slope_100x
        self.offset_1x = offset_1x
        self.offset_10x = offset_10x
        self.offset_100x = offset_100x
        self.std_concentration = std_concentration
        self.std_voltage_10x = std_voltage_10x
        self.blank_1x = blank_1x
        self.blank_10x = blank_10x
        self.blank_100x = blank_100x
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
        voltages = self.task.read(number_of_samples_per_channel=100)
        self.task.stop()
        avg_voltage = sum(voltages) / len(voltages)
        return avg_voltage

    def convert_to_concentration(self, voltage):
        '''
        Convert a voltage reading to concentration based on the current gain.
        Calculate slope from 400 ppb gain at 1x and use zero/offset
        for each gain.
        '''
        
        if self.gain == 1:
            concentration = self.slope_1x * voltage * 1000 + self.offset_1x
        elif self.gain == 10:
            concentration = self.slope_10x * voltage * 1000 + self.offset_10x
        elif self.gain == 100:
            concentration = self.slope_100x * voltage * 1000 + self.offset_100x
        return concentration

    def convert_to_conc_turner(self, voltage):
        """
        Convert a single voltage reading to concentration based on the current gain.
        Follows Turner technical note S-0243.
        https://docs.turnerdesigns.com/t2/doc/tech-notes/S-0243.pdf
        """
        if self.gain == 1:
            concentration = (voltage - self.blank_1x) * (self.slope_10x - self.blank_10x) / 10
        elif self.gain == 10:
            concentration = (voltage - self.blank_10x) / 10 * (self.slope_10x - self.blank_10x) / 10
        elif self.gain == 100:
            concentration = (voltage - self.blank_100x) / 100 * (self.slope_10x - self.blank_10x) / 10
        else:
            raise ValueError("Invalid gain setting")
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

    def close(self):
        """
        Stop and close DAQ tasks cleanly.
        """
        try:
            self.task.close()
        except Exception:
            logger.error("Failed to close task", exc_info=True)
        try:
            self.do_task.stop()
            self.do_task.close()
        except Exception:
            logger.error("Failed to close task", exc_info=True)