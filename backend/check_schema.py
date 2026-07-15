import sqlite3
conn = sqlite3.connect('D:\\fantasyfootballcrew\\backend\\ffc.db')
c = conn.cursor()
c.execute('PRAGMA table_info(teams)')
print('Teams:', {r[1] for r in c.fetchall()})
c.execute('PRAGMA table_info(leagues)')
print('Leagues:', {r[1] for r in c.fetchall()})
conn.close()
