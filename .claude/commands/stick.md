---
description: Dock reputation from an agent (/stick <agent> <points> "optional reason")
---
!python3 << 'EOF'
import os, json, sys, shlex
from urllib import request, error

parts = shlex.split(r'''$ARGUMENTS''')
if len(parts) < 2:
    print('Usage: /stick <agent> <points> "optional reason"')
    sys.exit(0)
agent = parts[0]
try:
    points = abs(int(parts[1]))
except ValueError:
    print(f"points must be a number, got {parts[1]!r}")
    sys.exit(0)
reason = " ".join(parts[2:]) if len(parts) > 2 else None

cwd = os.getcwd()
try:
    with request.urlopen("http://localhost:8000/api/projects", timeout=2) as r:
        projects = json.load(r)
except (error.URLError, TimeoutError) as e:
    print(f"DWB API unreachable: {e}")
    sys.exit(0)
project = next((p for p in projects if p.get("repo_path") and cwd.startswith(p["repo_path"])), None)
if not project:
    print(f"No DWB project matches cwd {cwd}")
    sys.exit(0)

body = json.dumps({"agent": agent, "delta": -points, "reason": reason}).encode()
req = request.Request(
    f"http://localhost:8000/api/projects/{project['id']}/scores/award",
    data=body, headers={"Content-Type": "application/json"}, method="POST",
)
try:
    with request.urlopen(req, timeout=3) as r:
        res = json.load(r)
    print(f"stick: {res['subject_name']} {res['delta']:+d} -> reputation {res['reputation']} (notified {res['broadcast_count']} agents)")
except error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
EOF
