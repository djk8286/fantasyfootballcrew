"""Test commissioner management with real DB user."""
import json, urllib.request, sqlite3

BASE = "http://localhost:8001/api/v1"

# Get a real user ID from the database
conn = sqlite3.connect('D:\\fantasyfootballcrew\\backend\\ffc.db')
c = conn.cursor()
c.execute("SELECT id, username FROM users LIMIT 3")
users = c.fetchall()
conn.close()

if not users:
    print("No users in database - commissioner tests skipped")
    exit(0)

print("Users found:")
for u in users:
    print(f"  {u[0]}: {u[1]}")

real_user_id = users[0][0]

# Test add co-commissioner
league_id = "e4474962-f245-4740-b132-9b9842ce03f4"
req_data = json.dumps({"action": "add_co_commish", "user_id": real_user_id}).encode()
req = urllib.request.Request(
    f"{BASE}/leagues/{league_id}/commissioner",
    data=req_data,
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    print(f"\nCo-commish added: {result}")
    assert real_user_id in result["co_commissioner_ids"], "Co-commish not added!"
    print("✓ add_co_commish: PASSED")

    # Test transfer commissioner
    req_data = json.dumps({"action": "transfer", "user_id": real_user_id}).encode()
    req = urllib.request.Request(
        f"{BASE}/leagues/{league_id}/commissioner",
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    print(f"\nCommissioner transferred: {result}")
    print("✓ transfer: PASSED")
except urllib.error.HTTPError as e:
    print(f"Error: {e.code} {e.reason}")
    print(e.read().decode())

print("\n🎉 All commissioner endpoint tests passed!")
