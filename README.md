# Underway Fluorimetry and GPS logging

This project acquires and logs data from a Turner Cyclops-7F rhodamine fluorometer
and a serial GPS stream. Fluorometer voltage is read using a NI-6008 USB DAQ.
100 voltage reads are taken at 1kHz and averaged for every polled reading.
GPS and fluorometer data are logged to a file and a SQLite3 database.

# Installation

* Clone the repository
* Copy `config-template.yaml` to `config.yaml` and edit config data.

if using uv for project/dependency management:

* Run the main fluorometer program `uv run main.py`

If using venv/pip:

* Create a virtual environment: `python -m venv .venv`
* Activate environment: `source .venv/bin/activate`
* Install dependencies: `python -m pip install .`
* Run the main fluorometer program `python -m main.py`

# Use

Run the `main.py` program. DAQ should start, 
logging information to the terminal and files specified.
Exit the program with `ctrl-C`.
