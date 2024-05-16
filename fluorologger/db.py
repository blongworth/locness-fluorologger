import sqlite3

def write_to_database(timestamp, gain, voltage, concentration):
    c.execute("INSERT INTO data VALUES (?, ?, ?, ?)", (timestamp, gain, voltage, concentration))
    conn.commit()
