# Path: app/config/__init__.py
# File: __init__.py
# Created: 2026-06-09
# Purpose: app.config package — Settings (this file) + versioned data submodules (session_phrases, etc.)
# Caller: app/database.py, app/services/*
# Callees: pydantic_settings, app.config.session_phrases
# Data In: .env file (settings)
# Data Out: Settings instance, re-exported submodules
# Last Modified: 2026-06-09

"""DWB-336 introduced `app/config/` as a versioned-data package
(session_phrases.py lives here). To keep `from app.config import settings`
working for every existing caller, the Settings class moved into this
package's __init__ when the standalone `app/config.py` was retired.

Anything that was previously imported from `app.config` is still imported
from `app.config` — only the on-disk layout changed.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_DATABASE: str = "local_agent_tracker"
    MYSQL_USER: str = "lat_user"
    MYSQL_PASSWORD: str = "lat_dev_password"
    MYSQL_ROOT_PASSWORD: str = "lat_root_password"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = True
    ADMIN_API_KEY: str = "lat-admin-CHANGE-ME-TO-RANDOM-64-CHAR-HEX"

    # DWB session idle sweeper (DWB-337). Disabled (interval=0) in tests so
    # the asyncio task doesn't fight with rolled-back transactions.
    IDLE_TIMEOUT_MINUTES: int = 60
    IDLE_SWEEP_INTERVAL_SECONDS: int = 300

    # DWB-449: age-based purge of captured inter-agent messages. Rows older
    # than this many days are deleted on each idle-sweeper cycle (the purge
    # rides the existing periodic loop; it is NOT tied to session close and
    # keys off created_at alone). 0 disables the purge.
    AGENT_MESSAGE_RETENTION_DAYS: int = 4

    # DWB-369: marker-file sweeper. Periodically cleans pending-* markers
    # whose worker died pre-SubagentStop AND finalized markers whose
    # hook_session has completed. Mirrors the idle_sweeper interval
    # convention - interval=0 disables, default 600s (10 min) is much
    # less aggressive than idle (5 min) because marker churn is slow.
    MARKER_STALE_MINUTES: int = 30
    MARKER_SWEEP_INTERVAL_SECONDS: int = 600

    # Jira (optional — empty disables the /api/jira/* endpoints)
    JIRA_BASE_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_CACHE_TTL_SECONDS: int = 60
    # DWB-356: Jira stores sprint membership in an instance-specific custom
    # field. Cloud defaults to customfield_10020; on-prem installs vary, so
    # this is overridable via .env. The normalizer reads this field name
    # off the issue payload to derive the active sprint name.
    JIRA_SPRINT_CUSTOMFIELD: str = "customfield_10020"
    # DWB-363: legacy Jira "Epic Link" customfield (pre next-gen projects).
    # Modern Jira surfaces the epic via parent.key / parent.fields.issuetype
    # (Roadvantage shape), so this is a fallback for older instances. The
    # extractor tries parent-as-Epic first and only consults this field if
    # the parent path didn't yield an epic.
    JIRA_EPIC_LINK_CUSTOMFIELD: str = "customfield_10014"

    @property
    def jira_configured(self) -> bool:
        return bool(self.JIRA_BASE_URL and self.JIRA_EMAIL and self.JIRA_API_TOKEN)

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
