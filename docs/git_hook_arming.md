# Arming a clone: the post-commit hook

> DWB-695. One local action per clone, and a way to prove it took.

## Why there is a step at all

Git deliberately refuses to execute hooks that arrive with a clone — doing so
would make `git clone` arbitrary code execution. `.git/` is never tracked, so
**no design makes a fresh clone armed with zero local action.** That is a
property of git, not a defect in DWB, and it is not going to be removed.

What *was* a defect is that an unarmed clone and a quiet one looked identical
from inside DWB. A hook that was never installed produces exactly the silence
of a hook that is installed with nothing to report. That is now answerable.

## Arm this clone

```bash
./scripts/install-git-hooks.sh
```

It symlinks `.git/hooks/post-commit` to the tracked
`scripts/hooks/post-commit`, then **verifies its own work** and exits non-zero
if the clone is still unarmed. An existing unrelated hook is moved aside to
`post-commit.bak.<timestamp>` rather than overwritten.

Nothing runs this for you, and nothing should.

## Check without changing anything

```bash
./scripts/install-git-hooks.sh --check    # exit 0 armed, 1 unarmed
```

## Check from DWB's side

```
GET /api/projects/{id}/hook-status
```

`armed` is **three-valued**, the same convention `gate-status` uses for
`all_passing`:

| `armed` | meaning |
|---|---|
| `true` | git will run a hook that reports to DWB |
| `false` | it will not — see `state` |
| `null` | **could not answer**: no `repo_path`, or a path this machine cannot read |

`null` is falsy, so `if armed` lands on the safe reading. Anything *acting* on
"unarmed" must test `is False` — "we could not look" must never be reported as
"it is off".

Read **`silence_means`** before concluding anything from `commit_rows`. Zero
rows means four different things depending on the state beside it, and only one
of them is about the work.

## The states, and why each is named

| `state` | what it means |
|---|---|
| `armed` | a post-commit hook is in the directory git uses, is executable, and posts to DWB |
| `no_hook` | nothing in the directory git uses |
| `hook_not_executable` | a hook is there and **git silently skips it**. The hint git prints goes to the committer's terminal, never to DWB |
| `foreign_hook` | a hook runs, but does not report to DWB. Running and reporting are different things |
| `unknown_no_repo_path` / `unknown_repo_unreadable` | DWB could not look |

### `core.hooksPath` is not used, deliberately

Setting it **replaces** the hooks directory rather than adding to it, so a
half-finished configuration switches `.git/hooks` off as well. The result is a
repository that looks configured, has eleven untouched sample hooks sitting
beside it, and runs nothing.

That failure is live on another repo today — which is why `hook-status` reports
`hooks_path_override` and `hooks_path_overrides_default` whenever it is set,
and says `DISABLES .git/hooks` in plain words.

## What a commit row holds

`authored_at` and `committed_at` are **separate** columns: a rebase or amend
moves one and not the other, and any later "was there a commit inside this
ticket's window" question is only as correct as the choice between them.

`changed_paths` includes **deletions** (unlike `code_pointers.commit_files`,
which excludes them because a vanished file cannot host a code pointer). A file
the work deleted is still evidence the work touched it.

`branch` is the only field that cannot be recovered later — a branch pointer
moves — so it arrives from the hook payload and is `NULL` when not reported.
Everything else the server reads back out of the repository, which is why the
hook contract did not have to change.

## The data is not lost

All commits remain readable from git, so rows are backfillable for any clone
that reaches the machine. Only commits in clones nobody ever pulls are
unrecoverable. Arming late costs much less than it sounds like.

## What this is not

There is **no detector** reading these rows, on purpose. Measured on this repo:
420 of 614 done tickets have no commit carrying their key — 68.4%. A detector
keyed on raw key-absence would penalise two thirds of all completed work. Any
such detector is a separate ticket, must state its own coverage, and must
respect the availability floor (`commit_record.within_commit_coverage`), which
returns `False` when there is no data rather than licensing a conclusion from
an empty table.
