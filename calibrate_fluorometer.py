import time
import statistics
from fluorologger.fluorometer import Fluorometer

def prompt_float(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a number.")

def measure_blank(fluor, gain):
    print("\n\nPlace the fluorometer in the blank.\n"
          " Press Enter to start 60s measurement.")
    input()
    print(f"\nSetting gain to {gain}x.")
    fluor.set_gain(gain)
    time.sleep(5)  # allow gain to settle
    print("\nMeasuring blank solution")
    voltages = []
    start = time.time()
    while time.time() - start < 60:
        v = fluor.read_voltage()
        voltages.append(v)
        print(".")
        time.sleep(0.5)
    mean_v = statistics.mean(voltages)
    std_v = statistics.stdev(voltages) if len(voltages) > 1 else 0.0
    print(f"\nBlank {gain}x: mean={mean_v:.5f} V, std={std_v:.5f} V")
    return mean_v

def measure_standard(fluor):
    print("\n\nPlace the fluorometer in the standard solution.\n"
          "Press Enter to start 60s measurement.")
    input()
    print("\nSetting gain to 10x.")
    fluor.set_gain(10)
    time.sleep(5)
    print("\nMeasuring standard solution")
    voltages = []
    start = time.time()
    while time.time() - start < 60:
        v = fluor.read_voltage()
        voltages.append(v)
        print(".")
        time.sleep(0.5)
    mean_v = statistics.mean(voltages)
    std_v = statistics.stdev(voltages) if len(voltages) > 1 else 0.0
    print(f"\nStandard 10x: mean={mean_v:.5f} V, std={std_v:.5f} V")
    return mean_v

def main():
    print("Fluorometer Calibration Script\n")
    std_conc = prompt_float("Enter rhodamine standard concentration (ppb): ")
    fluor = Fluorometer(
        slope_1x=1, slope_10x=1, slope_100x=1,  # dummy, not used here
        offset_1x=0, offset_10x=0, offset_100x=0,
        std_concentration=std_conc, std_voltage_10x=0,
        blank_1x=0, blank_10x=0, blank_100x=0,
        autogain=False, gain=1
    )
    try:
        blank_1x, std_1x = measure_blank(fluor, 1)
        blank_10x, std_10x = measure_blank(fluor, 10)
        blank_100x, std_100x = measure_blank(fluor, 100)
        std_voltage_10x, std_std_10x = measure_standard(fluor)
        # Save to file
        fname = input("\nEnter filename to save calibration (e.g. calibration.yaml): ")
        with open(fname, 'w') as f:
            f.write(f"rhodamine_standard_concentration: {std_conc}\n")
            f.write(f"blank_1x_mean: {blank_1x}\nblank_1x_std: {std_1x}\n")
            f.write(f"blank_10x_mean: {blank_10x}\nblank_10x_std: {std_10x}\n")
            f.write(f"blank_100x_mean: {blank_100x}\nblank_100x_std: {std_100x}\n")
            f.write(f"standard_10x_mean: {std_voltage_10x}\nstandard_10x_std: {std_std_10x}\n")
        print(f"\nCalibration data saved to {fname}")
    finally:
        fluor.close()

if __name__ == "__main__":
    main()
