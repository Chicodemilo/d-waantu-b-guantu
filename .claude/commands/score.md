---
description: Show an agent's score and recent ledger (/score <agent>)
---
!python3 << 'EOF'
import os, json, sys, shlex
from urllib import request, error, parse

parts = shlex.split(r'''$ARGUMENTS''')
if not parts:
    print("Usage: /score <agent>")
    sys.exit(0)
agent = parts[0]

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

qs = parse.urlencode({"agent": agent, "limit": 10})
url = f"http://localhost:8000/api/projects/{project['id']}/scores/agent?{qs}"
try:
    with request.urlopen(url, timeout=10) as r:
        d = json.load(r)
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
    sys.exit(0)

print(f"{agent}: reputation {d['reputation']}  sprint {d['sprint_delta']:+d}  influence {d['influence']}")
ledger = d.get("ledger", [])
if not ledger:
    print("  (no score events)")
for e in ledger[:10]:
    rev = " [reverted]" if e.get("reverted_by") else ""
    actor = f" by {e['actor_name']}" if e.get("actor_name") else ""
    print(f"  {e['delta']:+d}  {e['trigger_type']}{actor}  {e.get('reason') or '-'}{rev}")
EOF
