import sqlite3
conn = sqlite3.connect('D:\\fantasyfootballcrew\\backend\\ffc.db')
c = conn.cursor()
# Fix existing CPU teams
c.execute("UPDATE teams SET is_cpu = 1 WHERE owner_id = 'cpu'")
count = c.rowcount
conn.commit()
conn.close()
print(f"Fixed {count} existing CPU teams: set is_cpu=1")
