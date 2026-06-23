---
description: Send a team-lead channel message (/tl @Archie_X <msg> = direct, /tl <msg> = broadcast to all archies)
---
!python3 << 'EOF'
import os, json, sys
from urllib import request, error

API = "http://localhost:8000"

raw = r'''$ARGUMENTS'''.strip()
if not raw:
    print('Usage: /tl @Archie_X your message   (direct, but all archies can see it)')
    print('       /tl your message              (broadcast to every archie)')
    sys.exit(0)

# Parse: a leading @Name token => direct; otherwise broadcast. Body kept verbatim
# (no shlex) so apostrophes/quotes in the message survive.
if raw.startswith('@'):
    first, _, rest = raw.partition(' ')
    recipient_name = first[1:].strip()
    body = rest.strip()
    if not recipient_name or not body:
        print('Usage: /tl @Archie_X your message')
        sys.exit(0)
else:
    recipient_name = None
    body = raw

def get(path, timeout=3):
    with request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)

cwd = os.getcwd()
try:
    projects = get("/api/projects", timeout=2)
    agents = get("/api/agents", timeout=3)
except (error.URLError, TimeoutError) as e:
    print(f"DWB API unreachable: {e}")
    sys.exit(0)

project = next((p for p in projects if p.get("repo_path") and cwd.startswith(p["repo_path"])), None)
if not project:
    print(f"No DWB project matches cwd {cwd}")
    sys.exit(0)

TL_ROLES = ("team-lead", "team_lead")
team_leads = [a for a in agents if a.get("role") in TL_ROLES and a.get("is_active")]

# Sender = the active team-lead of the current project.
sender = next((a for a in team_leads if a.get("project_id") == project["id"]), None)
if not sender:
    print(f"No active team-lead found on {project.get('prefix','this project')} to send as")
    sys.exit(0)

to_agent_id = None
if recipient_name is not None:
    match = next((a for a in team_leads if a.get("name", "").lower() == recipient_name.lower()), None)
    if not match:
        others = sorted(a["name"] for a in team_leads if a["id"] != sender["id"])
        print(f"No active team-lead named {recipient_name!r}.")
        if others:
            print("Archies you can message: " + ", ".join(others))
        sys.exit(0)
    if match["id"] == sender["id"]:
        print("That's you. Pick another archie, or drop the @ to broadcast.")
        sys.exit(0)
    to_agent_id = match["id"]

payload = json.dumps({"from_agent_id": sender["id"], "to_agent_id": to_agent_id, "body": body}).encode()
req = request.Request(API + "/api/tl-channel", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
try:
    with request.urlopen(req, timeout=3) as r:
        res = json.load(r)
    m = res["message"]
    dest = m["to_agent_name"] if not m["is_broadcast"] else "ALL archies"
    print(f"Sent channel message #{m['id']} from {m['from_agent_name']} -> {dest} "
          f"(pinged {res['alert_count']} archie{'s' if res['alert_count'] != 1 else ''})")
except error.HTTPError as e:
    try:
        detail = (json.loads(e.read().decode() or "{}") or {}).get("detail") or ""
    except Exception:
        detail = ""
    print(detail or f"send failed (HTTP {e.code})")
EOF
