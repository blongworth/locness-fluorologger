import time
import statistics
import matplotlib.pyplot as plt
from fluorologger.fluorometer import Fluorometer

def plot_voltage_vs_time(times, voltages, ax=None):
    if ax is None:
        plt.ion()
        fig, ax = plt.subplots()
    ax.clear()
    ax.plot(times, voltages, marker='o')
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Voltage (V)")
    ax.set_title("Voltage vs Time")
    plt.draw()
    plt.pause(0.01)
    return ax

def prompt_float(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a number.")

def measure_blank(fluor, gain):
    while True:
        print("\n\nPlace the fluorometer in the blank.\n"
              " Press Enter to start 60s measurement.")
        input()
        print(f"\nSetting gain to {gain}x.")
        fluor.set_gain(gain)
        time.sleep(5)  # allow gain to settle
        print("\nMeasuring blank solution", end="")
        voltages = []
        times = []
        start = time.time()
        ax = None
        while time.time() - start < 60:
            v = fluor.read_voltage()
            t = time.time() - start
            voltages.append(v)
            times.append(t)
            print(".", end="")
            ax = plot_voltage_vs_time(times, voltages, ax)
            time.sleep(0.5)
        plt.ioff()
        mean_v = statistics.mean(voltages)
        std_v = statistics.stdev(voltages) if len(voltages) > 1 else 0.0
        print(f"\nBlank {gain}x: mean={mean_v:.5f} V, std={std_v:.5f} V")
        resp = input("Accept this measurement? (y/n): ").strip().lower()
        if resp == 'y':
            return mean_v, std_v
        print("Repeating blank measurement...")

def measure_standard(fluor, gain):
    while True:
        print("\n\nPlace the fluorometer in the standard solution.\n"
              "Press Enter to start 60s measurement.")
        input()
        print(f"\nSetting gain to {gain}x.")
        fluor.set_gain(gain)
        time.sleep(5)
        print("\nMeasuring standard solution", end="")
        voltages = []
        times = []
        start = time.time()
        ax = None
        while time.time() - start < 60:
            v = fluor.read_voltage()
            t = time.time() - start
            voltages.append(v)
            times.append(t)
            print(".", end="")
            ax = plot_voltage_vs_time(times, voltages, ax)
            time.sleep(0.5)
        plt.ioff()
        mean_v = statistics.mean(voltages)
        std_v = statistics.stdev(voltages) if len(voltages) > 1 else 0.0
        print(f"\nStandard {gain}x: mean={mean_v:.5f} V, std={std_v:.5f} V")
        resp = input("Accept this measurement? (y/n): ").strip().lower()
        if resp == 'y':
            return mean_v, std_v
        print("Repeating standard measurement...")

def main():
    print("Fluorometer Calibration Script\n")
    std_conc = prompt_float("Enter rhodamine standard concentration (ppb): ")
    std_gain = int(prompt_float("Enter gain for standard calibration (1, 10, or 100): "))
    fluor = Fluorometer(
        std_concentration=std_conc, std_voltage=0, std_gain=1,
        blank_1x=0, blank_10x=0, blank_100x=0,
        autogain=False, gain=1
    )
    try:
        blank_100x, std_100x = measure_blank(fluor, 100)
        blank_10x, std_10x = measure_blank(fluor, 10)
        blank_1x, std_1x = measure_blank(fluor, 1)
        std_voltage, std_std = measure_standard(fluor, std_gain)

        # Print summary
        print("\n--- Calibration Summary ---")
        print(f"Blank 1x:    mean = {blank_1x:.5f} V, std = {std_1x:.5f} V")
        print(f"Blank 10x:   mean = {blank_10x:.5f} V, std = {std_10x:.5f} V")
        print(f"Blank 100x:  mean = {blank_100x:.5f} V, std = {std_100x:.5f} V")
        print(f"Standard {std_gain}x: mean = {std_voltage:.5f} V, std = {std_std:.5f} V")
        print(f"Sensitivity: {std_conc / (std_voltage - blank_1x):.5f} ppb/V")
        print("--------------------------\n")

        # Save to file
        fname = input("\nEnter filename to save calibration (e.g. calibration.txt): ")
        with open(fname, 'w') as f:
            f.write(f"rhodamine_standard_concentration: {std_conc}\n")
            f.write(f"blank_1x_mean: {blank_1x}\nblank_1x_std: {std_1x}\n")
            f.write(f"blank_10x_mean: {blank_10x}\nblank_10x_std: {std_10x}\n")
            f.write(f"blank_100x_mean: {blank_100x}\nblank_100x_std: {std_100x}\n")
            f.write(f"standard_{std_gain}x_mean: {std_voltage}\nstandard_{std_gain}x_std: {std_std}\n")
            f.write(f"sensitivity: {std_conc / (std_voltage - blank_1x)}\n")
            f.write(f"std_gain: {std_gain}\n")
        print(f"\nCalibration data saved to {fname}")
    finally:
        fluor.close()

if __name__ == "__main__":
    main()
