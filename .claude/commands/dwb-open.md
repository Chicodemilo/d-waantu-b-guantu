---
description: Open a DWB session for the current project (deterministic Layer 3 escape hatch, DWB-381)
---
!python3 << 'EOF'
import os, json, sys, datetime
from urllib import request, error

cwd = os.getcwd()
try:
    with request.urlopen("http://localhost:8000/api/projects", timeout=10) as r:
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

now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
body = json.dumps({
    "project_id": project["id"],
    "opened_at": now,
    "open_method": "slash",
    "open_phrase": "/dwb-open",
}).encode()
req = request.Request(
    "http://localhost:8000/api/sessions/open",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with request.urlopen(req, timeout=10) as r:
        result = json.load(r)
    print(f"Opened DWB session {result['id']} for {project['prefix']} (method=slash)")
except error.HTTPError as e:
    if e.code == 409:
        body = json.loads(e.read().decode() or "{}")
        existing = body.get("dwb_session_id") or body.get("id") or "unknown"
        print(f"DWB session already open for {project['prefix']} (id={existing})")
    else:
        print(f"HTTP {e.code}: {e.read().decode()}")
EOF
