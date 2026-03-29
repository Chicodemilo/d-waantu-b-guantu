"""Run the token attribution scanner and return structured results."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
VENV_PYTHON = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "python"


def run_token_scan(project_id: int) -> dict:
    """Run attribute_tokens.py for a project and return the parsed summary.

    Returns a dict with keys: sessions_found, sessions_attributed,
    total_tokens, attributions, error (if any).
    """
    script = SCRIPTS_DIR / "attribute_tokens.py"
    python = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable

    result = subprocess.run(
        [python, str(script), "--project-id", str(project_id)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = result.stdout or ""

    # The script outputs JSON summary as the last line containing '{'
    summary = None
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                summary = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if summary is None:
        return {
            "sessions_found": 0,
            "sessions_attributed": 0,
            "total_tokens": 0,
            "attributions": [],
            "error": f"No JSON summary in output. stderr: {(result.stderr or '')[:500]}",
        }

    attributions = []
    for d in summary.get("details", []):
        attributions.append({
            "agent": d.get("agent", ""),
            "ticket_key": d.get("ticket_key", ""),
            "tokens": d.get("tokens", 0),
        })

    return {
        "sessions_found": summary.get("processed", 0),
        "sessions_attributed": summary.get("attributed", 0),
        "total_tokens": summary.get("total_tokens", 0),
        "attributions": attributions,
    }
