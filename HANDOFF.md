# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-09-15, mid-day; CC session cycling for display-mode relaunch. DWB session 109 LEFT OPEN intentionally - work continues after relaunch)

- **S80 (CLOSED, 6/6): Nodes Phase 1.** All tickets done with review evidence, write-on-close gate passed all participants. Commits: 7b9d013 (phase-1 checkpoint), 594276e (rename-prune fix DWB-525), 02496b7 (TF-IDF weight + node stoplist DWB-522). Gated test run posted 1689/1689 green. Final renodify: 3744 nodes / 69.6k pointers / 169 suppressed; top-20 verified specific (contract, roster, command, index, ticket-key tier). The index is PROVEN - Miles's hold on the visual phase is lifted.
- **Relaunch context (why this session ended):** teammates must render as native iTerm2 panes. Proven this session: display mode locks at CC session START (PaneTest spawned after a settings flip, got no pane). CC binary upgraded 2.1.181 -> 2.1.272; `teammateMode: "iterm2"` set in ~/.claude/settings.json. FIRST SPAWN of the new session is the test: if no iTerm2 pane appears, it2 CLI (0.2.3, on PATH) + iTerm2 Python API were verified working today, so suspect CC-side - tell Miles.
- **VTC feedback batch (from Miles's other machine's lane):** filed as DWB-528..532, backlog, specs in tickets. B4 withdrawn (their bug). DWB-530 has FOUR independent 404-ambiguity repros (2 VTC, 2 mine incl. /api/comments route shape). DWB-532 = GET agent memory endpoint; **Miles has a "funny idea" about it - REMIND HIM once 532 is built.**
- **Pending Miles decisions (numbered asks he hasn't answered):** #2 stick-redemption rule (endorsed w/ teeth: API-verified memory note citing stick ledger event id -> auto half back, once, 48h window) - if yes, ticket as DWB-537 into S81. #3 S81 slate approval: DWB-534/535/536 (nodes visual: cloud page, detail panel, match search - frontend) + pull 528-530/532/533 + optional 537. NOT FILED - file on his yes. Also undecided: playbook-trim bless/discard on his OTHER clone (~/Dev/d-waantu-b-guantu, different machine, uncommitted working-tree trim deployed to that instance's lanes) - DWB-531 stays backlog until settled.
- **Also pending discussion (NOT authorized work):** getting nodes into agent context (retrieval already feeds spawn-prepare relevant_lessons; Miles wants to discuss more).

## Next session, in order
1. Identity flow, confirm DWB session 109 still open (regex open attempt will 409 -> fine).
2. Spawn ONE worker, verify an iTerm2 PANE opens (not just a panel row). Then full team.
3. Collect Miles's numbered answers (#2, #3 above); file S81 tickets (next ticket_number: 534; 533 consumed by auto-mint), create S81 sprint under epic 53, respawn Barry_DWB (21) + Stan (38) + a frontend worker (Freddie 19 on roster; Pixel convention also fine) per full spawn flow.
4. S81 lanes: frontend = visual tickets; Barry = fix batch + 537; Stan = 533 test coverage.

## Backlog
DWB-514 (agent DELETE 500 on FK children), DWB-516 (recap re-cut), DWB-515/521 (auto test tickets; NOTE: S80 close auto-assigned DWB-533 to dark Sage on ancient sprint 23 - I rehomed it to Stan/backlog; add that repro to 515/521 scope), DWB-528..532 (VTC batch), DWB-531 (blocked on trim decision).

## Gotchas (carry forward)
- Display mode reads at CC session start, NOT at spawn. Settings flips mid-session do nothing.
- SendMessage routes by LITERAL name; check inbox names before concluding silence.
- Sprint-close auto-mints next test ticket: reserve ticket numbers AFTER close, and CHECK the minted ticket's assignee+sprint (stale-Sage/ancient-sprint bug).
- Workers idle instead of answering shutdown_requests; nudge with the request_id, or reissue fresh.
- Bash tool cwd can stick from earlier commands - pin git with -C.
- /api/comments?ticket_id=N is the comments route; /api/tickets/{id}/comments does NOT exist (bare 404).
- Uvicorn (8000, --reload confirmed) + Vite (5173) left RUNNING, MySQL container up.

## Team
ALL SHUT DOWN clean 15:33 (Barry_DWB, Stan; session-completes verified in memory files before termination; PaneTest throwaway also terminated). Scores: Barry +2, Stan +2 carrots this session. CC teams do not survive sessions - respawn per playbook (spawn-prepare + marker + paste memory_full), never message old roster names first.
