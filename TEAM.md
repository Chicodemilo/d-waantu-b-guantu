# Team — D'Waantu B'Guantu

> This file is the live roster for this project. It starts with mandatory agents and grows as the TL spins up workers. Update it when the team composition changes.

## Mandatory (always present)

| Name | Role | Duty | Playbook |
|------|------|------|----------|
| Archie | team-lead | Plans sprints, assigns tickets, reviews work, orchestrates agents | `.claude/agents/team-lead.md` |
| Pam | pm | Tracks tickets, monitors progress, sprint health, alerts, failure logging | `.claude/agents/pm.md` |

## Workers (added when team spins up)

| Name | Role | Duty | Playbook |
|------|------|------|----------|
| | | | |

> All agents also receive the general worker playbook: `.claude/agents/worker.md`

## Naming Convention

Name agents by **matching as many leading letters of the role as possible to a real human name.** Three-letter matches are better than two. This makes it easy to remember who does what.

**Fixed names** (always use these):
| Role | Default Name |
|------|-------------|
| pm | **Pam** |
| tester | **Chester** |

**Standard roles:**
| Role | Default Name |
|------|-------------|
| frontend-worker | **Freddie** |
| backend-worker | **Barry** |
| system-ops | **Sylvie** |

**Custom roles** (follow the same leading-letters pattern):
| Role | Example Names |
|------|--------------|
| designer | **Des**mond, **Des**iree |
| researcher | **Res**a, **Re**my |
| devops | **Dev**on, **Dev**in |
| analyst | **Ana**stasia, **An**dre |
| reviewer | **Rev**a, **Re**ggie |
| security | **Sec**ily, **Seb**astian |
| database | **Da**rcy, **Dan**te |
| architect | **Arc**hie, **Ari**adne |
| mobile | **Mo**ira, **Mor**ris |
| docs-writer | **Dol**ores, **Dom**inic |
| data-engineer | **Da**phne, **Dan**iel |
| infra | **Ing**rid, **Irv**ing |
| qa | **Qu**inn |
| ux | **Ur**sula |
| api-worker | **Apr**il |
| migrator | **Mi**tch, **Min**a |
| performance | **Per**cy, **Pet**ra |
| scheduler | **Sca**rlett |

If you spawn a role not listed here, follow the pattern: match as many leading letters as possible to a real human name. Three letters is ideal, two is the minimum.

The `role` field in the DB maps to the Claude teammate name (e.g., role="pm" → @pm). The `name` field is the display name (e.g., "Pam").

## Project Context

- **DWB Project ID:** 1
- **Prefix:** DWB
- **Repo:** /Users/mchick/Dev/d-waantu_b-guantu
- **Jira:** none
