---
description: Send a team-lead channel message (/tl @Archie_X <msg> = direct, /tl <msg> = broadcast to all archies)
---
!python3 << 'EOF'
import os, json, sys
from urllib import request, error

API = "http://localhost:8000"

# DWB-508: every failure is LOUD. This script's old error paths printed a note
# and exited 0, so a dropped send looked like success to the harness (fresh
# repro: IND 2026-09-10, script ran clean, nothing landed on the channel).
# Delivery is confirmed ONLY by the top-level `id` in the send response (the
# backend guarantees it on success); anything else is a hard failure: message
# on stderr, exit 1.
def fail(msg):
    print(f"/tl SEND FAILED: {msg}", file=sys.stderr)
    sys.exit(1)

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
        fail('malformed direct send - use: /tl @Archie_X your message')
else:
    recipient_name = None
    body = raw

def get(path, timeout=10):
    with request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)

cwd = os.getcwd()
try:
    projects = get("/api/projects", timeout=10)
    agents = get("/api/agents", timeout=10)
except (error.URLError, TimeoutError, OSError) as e:
    fail(f"DWB API unreachable: {e}")

project = next((p for p in projects if p.get("repo_path") and cwd.startswith(p["repo_path"])), None)
if not project:
    fail(f"no DWB project matches cwd {cwd}")

TL_ROLES = ("team-lead", "team_lead")
team_leads = [a for a in agents if a.get("role") in TL_ROLES and a.get("is_active")]

# Sender = the active team-lead of the current project.
sender = next((a for a in team_leads if a.get("project_id") == project["id"]), None)
if not sender:
    fail(f"no active team-lead found on {project.get('prefix','this project')} to send as")

to_agent_id = None
if recipient_name is not None:
    match = next((a for a in team_leads if a.get("name", "").lower() == recipient_name.lower()), None)
    if not match:
        others = sorted(a["name"] for a in team_leads if a["id"] != sender["id"])
        hint = (" Archies you can message: " + ", ".join(others)) if others else ""
        fail(f"no active team-lead named {recipient_name!r}.{hint}")
    if match["id"] == sender["id"]:
        fail("that's you. Pick another archie, or drop the @ to broadcast.")
    to_agent_id = match["id"]

payload = json.dumps({"from_agent_id": sender["id"], "to_agent_id": to_agent_id, "body": body}).encode()
req = request.Request(API + "/api/tl-channel", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
try:
    with request.urlopen(req, timeout=10) as r:
        res = json.load(r)
except error.HTTPError as e:
    try:
        detail = (json.loads(e.read().decode() or "{}") or {}).get("detail") or ""
    except Exception:
        detail = ""
    fail(detail or f"HTTP {e.code} from the send endpoint")
except (error.URLError, TimeoutError, OSError) as e:
    fail(f"could not reach the send endpoint: {e}")
except ValueError as e:
    fail(f"unparseable response from the send endpoint: {e}")

# DWB-508: the persisted row's id is the delivery receipt. No id = NOT delivered,
# whatever the HTTP status said.
msg_id = res.get("id")
if not msg_id:
    fail(f"send endpoint returned no message id - treat as NOT delivered (response: {json.dumps(res)[:200]})")

m = res.get("message") or {}
dest = "ALL archies" if m.get("is_broadcast") else (m.get("to_agent_name") or "?")
alert_count = res.get("alert_count", 0)
print(f"Sent channel message #{msg_id} from {m.get('from_agent_name', sender['name'])} -> {dest} "
      f"(pinged {alert_count} archie{'s' if alert_count != 1 else ''})")
EOF
