---
description: Close the active DWB session for the current project (deterministic Layer 3 escape hatch, DWB-381)
---
!python3 << 'EOF'
import os, json, sys
from urllib import request, error

cwd = os.getcwd()
try:
    with request.urlopen("http://localhost:8000/api/projects", timeout=2) as r:
        projects = json.load(r)
except (error.URLError, TimeoutError) as e:
    print(f"DWB API unreachable: {e}")
    sys.exit(0)

project = next(
    (p for p in projects if p.get("repo_path") and cwd.startswith(p["repo_path"])),
    None,
)
if not project:
    print(f"No DWB project matches cwd {cwd}")
    sys.exit(0)

try:
    with request.urlopen(
        f"http://localhost:8000/api/projects/{project['id']}/sessions?limit=20",
        timeout=2,
    ) as r:
        sessions = json.load(r)
except (error.URLError, TimeoutError) as e:
    print(f"DWB API unreachable: {e}")
    sys.exit(0)

active = next((s for s in sessions if s.get("closed_at") is None), None)
if not active:
    print(f"No active DWB session for {project['prefix']}")
    sys.exit(0)

body = json.dumps({
    "close_method": "slash",
    "close_reason": "explicit",
    "close_phrase": "/dwb-close",
}).encode()
req = request.Request(
    f"http://localhost:8000/api/sessions/{active['id']}/close",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with request.urlopen(req, timeout=2) as r:
        json.load(r)
    print(f"Closed DWB session {active['id']} for {project['prefix']} (method=slash)")
except error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
EOF
