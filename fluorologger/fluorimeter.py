import nidaqmx
from nidaqmx.constants import AcquisitionType, TerminalConfiguration, LineGrouping
import time

# TODO: read voltage as HW timed burst
#
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
        #self.task.do_channels.add_do_chan("fluor/port0/line0:1", line_grouping=LineGrouping.CHAN_PER_LINE)

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
        if new_gain != self.gain:
            self.gain = new_gain
            self.last_gain_change = current_time
            if self.gain == 1:
                self.task.write([False, False])
            if self.gain == 10:
                self.task.write([True, False])
            if self.gain == 100:
                self.task.write([False, True])
            time.sleep(self.gain_change_delay)

