import sqlite3


with open('resources/lexitron_thai.txt') as f:
    entries = [entry.strip() for entry in f.readlines() if entry.strip()]

conn = sqlite3.connect('resources/dictionary.db')
c = conn.cursor()

c.execute('CREATE TABLE IF NOT EXISTS lexitron_thai (id INTEGER PRIMARY KEY, entry TEXT)')
c.execute('CREATE INDEX IF NOT EXISTS idx_entry ON lexitron_thai(entry)')

c.executemany('INSERT INTO lexitron_thai (entry) VALUES (?)', [(entry,) for entry in entries])

conn.commit()
conn.close()