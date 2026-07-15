"""Test the avatar PATCH endpoint."""
import json, urllib.request

BASE = "http://localhost:8001/api/v1"

# 1. Get league teams
resp = urllib.request.urlopen(f"{BASE}/teams/league/e4474962-f245-4740-b132-9b9842ce03f4")
teams = json.loads(resp.read())
human_team = [t for t in teams if t["owner_id"] != "cpu"]
if not human_team:
    print("No human teams found")
    exit(1)

team_id = human_team[0]["id"]
print(f"Testing PATCH on team: {human_team[0]['name']} (id: {team_id})")

# 2. Create a PATCH request
req = urllib.request.Request(
    f"{BASE}/teams/{team_id}",
    data=json.dumps({"avatar_url": "ffc-avatar:helmet-red"}).encode(),
    headers={"Content-Type": "application/json"},
    method="PATCH"
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"Avatar set: {result['avatar_url']}")

# 3. Verify via GET
resp = urllib.request.urlopen(f"{BASE}/teams/{team_id}")
team = json.loads(resp.read())
print(f"Verified via GET: avatar_url = {team['avatar_url']}")
assert team['avatar_url'] == 'ffc-avatar:helmet-red', "Avatar not persisted!"
print("PATCH test: PASSED")

# 4. Test claim endpoint on a CPU team
cpu_team = [t for t in teams if t["owner_id"] == "cpu"][0]
print(f"\nTesting CLAIM on CPU team: {cpu_team['name']} (id: {cpu_team['id']})")
req = urllib.request.Request(
    f"{BASE}/teams/{cpu_team['id']}/claim",
    data=json.dumps({"user_id": "test-user"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"Claimed! owner_id={result['owner_id']}, is_cpu={result['is_cpu']}")
assert result["owner_id"] == "test-user", "Owner not updated!"
assert result["is_cpu"] == False, "is_cpu should be false after claim!"
print("CLAIM test: PASSED")

# 5. Test commissioner management - add co-commissioner
league_id = "e4474962-f245-4740-b132-9b9842ce03f4"
req = urllib.request.Request(
    f"{BASE}/leagues/{league_id}/commissioner",
    data=json.dumps({"action": "add_co_commish", "user_id": "test-user"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"\nCo-commish added: commissioner_id={result['commissioner_id']}, co_commish_ids={result['co_commissioner_ids']}")
assert "test-user" in result["co_commissioner_ids"], "Co-commish not added!"
print("COMMISSIONER test: PASSED")

print("\n🎉 All endpoint tests passed!")
