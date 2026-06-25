---
description: Award reputation to an agent (/carrot <agent> <points> "optional reason")
allowed-tools: Bash
---
```!
python3 << 'PYEOF'
import os, json, sys, shlex
from urllib import request, error

parts = shlex.split(r'''$ARGUMENTS''')
if len(parts) < 2:
    print('Usage: /carrot <agent> <points> "optional reason"')
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
    with request.urlopen("http://localhost:8000/api/projects", timeout=10) as r:
        projects = json.load(r)
except (error.URLError, TimeoutError) as e:
    print(f"DWB API unreachable: {e}")
    sys.exit(0)
project = next((p for p in projects if p.get("repo_path") and cwd.startswith(p["repo_path"])), None)
if not project:
    print(f"No DWB project matches cwd {cwd}")
    sys.exit(0)

body = json.dumps({"agent": agent, "delta": points, "reason": reason}).encode()
req = request.Request(
    f"http://localhost:8000/api/projects/{project['id']}/scores/award",
    data=body, headers={"Content-Type": "application/json"}, method="POST",
)
try:
    with request.urlopen(req, timeout=10) as r:
        res = json.load(r)
    print(f"carrot: {res['subject_name']} {res['delta']:+d} -> reputation {res['reputation']} (notified {res['broadcast_count']} agents)")
except error.HTTPError as e:
    try:
        detail = (json.loads(e.read().decode() or "{}") or {}).get("detail") or ""
    except Exception:
        detail = ""
    msg = detail or f"request failed (HTTP {e.code})"
    if e.code == 404 and "agent" in msg.lower():
        try:
            with request.urlopen(f"http://localhost:8000/api/projects/{project['id']}/scores", timeout=10) as r2:
                names = sorted(n for n in (row.get("agent_name") for row in json.load(r2)) if n)
            if names:
                msg += f"\nAgents on {project.get('prefix','this project')}: " + ", ".join(names)
        except Exception:
            pass
    print(msg)
PYEOF
```

Report the result of the command above back to me in one short line: the agent, the +N reputation change, and their new total (or the error message if it failed). Do nothing else.
