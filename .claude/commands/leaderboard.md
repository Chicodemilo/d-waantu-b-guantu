---
description: Show the project scoring leaderboard (/leaderboard)
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
project = next((p for p in projects if p.get("repo_path") and cwd.startswith(p["repo_path"])), None)
if not project:
    print(f"No DWB project matches cwd {cwd}")
    sys.exit(0)

url = f"http://localhost:8000/api/projects/{project['id']}/scores"
try:
    with request.urlopen(url, timeout=3) as r:
        rows = json.load(r)
except error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
    sys.exit(0)

print(f"{project['prefix']} leaderboard")
print(f"  {'agent':14} {'rep':>4} {'sprint':>7} {'infl':>5}")
for r in rows:
    print(f"  {r['agent_name']:14} {r['reputation']:>4} {r['sprint_delta']:>+7} {r['influence']:>5}")
EOF
