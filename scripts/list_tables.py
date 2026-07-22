import sqlite3
import os
p = os.path.join(os.path.dirname(__file__), '..', 'smartcart.db')
p = os.path.abspath(p)
print('DB PATH:', p)
conn = sqlite3.connect(p)
cur = conn.cursor()
cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','index') ORDER BY type, name")
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
