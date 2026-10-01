# Path: app/services/memory_format.py
# File: memory_format.py
# Created: 2026-09-30 (DWB-594)
# Purpose: The ONE understanding of memory.md's on-disk format. Splits a file
#          into candidate entries (DWB-594's snapshot) and renders entries back
#          to that same format (DWB-595's revert). Pure text: no database, no
#          schema, no imports from the memory store.
# Caller: app/services/* for DWB-594 (adopt) and DWB-595 (revert)
# Callees: stdlib only
# Data In: memory.md text, or a list of MemoryEntry
# Data Out: list[MemoryEntry], or memory.md text
# Last Modified: 2026-10-01 (DWB-620: a write-stamp ends its section and is
#                recognised without seconds or a dash separator)

"""One format module, imported by both the splitter and the renderer.

PAM'S RULE, AND IT IS WHY THIS FILE EXISTS RATHER THAN TWO PRIVATE PARSERS: a
splitter and a renderer that agree are the only proof that either is right. Two
independent understandings of this format would disagree, and the disagreement
surfaces only on a revert-after-adopt - the least exercised path in the lane and
the one nobody runs by hand.

NARROWED, BECAUSE THE RULE AS FIRST WRITTEN IS TOO STRONG AND THE GAP IS REAL:
**agreement is NECESSARY, NOT SUFFICIENT.** The round-trip identity
`split(render(entries)) == entries` runs the SAME splitter on both passes while
the renderer echoes whatever it was handed, so the two halves still agree when
the splitter alone is wrong - they just agree about the wrong thing. Proved, not
argued: loosening the bullet pattern to swallow nested sub-bullets is a genuine
bug (a sub-point handed to an agent stripped of the point it qualifies is
unanswerable) and every round-trip test, plus the whole corpus, passed.

So the round trip is a CONSISTENCY check and the granularity tests are the
CORRECTNESS checks, and neither substitutes for the other. The general form,
worth carrying past this file: a consistency check between two halves needs
ground-truth assertions on each half independently, or it certifies a shared
mistake.

THERE IS NO SINGLE "EXISTING STRUCTURE", WHICH IS THE THING THAT MAKES THIS
HARDER THAN IT LOOKS. Measured across every real memory.md in this repo, two
organising schemes coexist:

  * APPEND LOGS - blocks delimited by `## <ISO 8601>` write-headings, the shape
    the append endpoint produces.
  * TOPICAL FILES - what a condense produces: `# Memory - <name>`, then
    `## Topic` / `### Subtopic`, then content. Here the ISO heading is a
    PROVENANCE MARKER sitting at the top of the file, not a delimiter, and a
    file can carry several stacked with empty bodies (a condense of a condense).

Measured across every real memory.md in this repo at the time of writing, which
is the evidence for every choice below:

    agent        iso_hdr  topic_hdr  bullets  nested  paragraphs
    Archie_DWB         2         12       70       0           3
    Barry_DWB          3         15        0       0           3
    Dolores            2          8       35       0           1
    Freddie            1         13       66       0           1
    Pam_DWB            3         12       45       6           7
    Sage              13          3       10       7           4
    Stan               5          3       32       4           0
    Sylvie            11          4       13       8           7
    TOTAL             40         70      271      25          26

Topic headings outnumber ISO headings 70 to 40, and six of the eight files are
majority-topical. A splitter keyed on ISO headings therefore returns ONE
candidate for Barry_DWB's 202-line file - which is precisely the "giant context
list" the whole lane exists to prevent, produced by a splitter that would look
correct in review and pass its own tests.

Read the `bullets` column against `topic_hdr` before reaching for a
heading-based split again: that is the number that settles it.

THE CANDIDATE IS THE BULLET, NOT THE BLOCK. Real files hold 271 top-level
bullets against 110 heading blocks. A heading block routinely carries ten
unrelated lessons, and DWB-594's decide phase is ONE entry and ONE question, so
splitting at block granularity forces one answer to ten questions. It also
breaks "on uncertainty, tier down": asked about a block, an agent tiers to its
weakest member and the good lessons sink with it.

The heading chain rides along as CONTEXT on each entry rather than becoming an
entry of its own. Nobody is ever asked to tier a timestamp or a section title.

ROUND-TRIPPING, STATED PRECISELY BECAUSE THE WRONG ASSERTION PASSES WHILE
MEANING NOTHING:

  * ``split(render(entries)) == entries`` IS an identity, and it is the test
    that catches the two halves disagreeing.
  * ``render(split(text)) == text`` is NOT achievable and is not asserted. A
    revert deliberately reorders (by tier, then score) and deliberately drops at
    the ceiling. A test demanding byte equality would have to be weakened later,
    and a weakened round-trip test is worse than none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A write-heading stamped by the memory endpoints. Both separators are real and
# both appear in live files: session_complete writes an EM DASH ("— session
# <id>"), condense writes a HYPHEN ("- condensed"). A parser that knows only one
# silently treats the other as a topic heading, which turns provenance into a
# candidate an agent is then asked to tier.
# DWB-620 DEFECT B: this pattern used to require SECONDS and to permit trailing
# text only after a dash separator. A live heading written by hand,
# `## 2026-09-14T18:37 DWB-520 (id 1460, S79/157) -> in_review`, satisfies
# neither condition, so it fell through to ANY_HEADING and was PUSHED onto the
# section stack as a topic. A write-heading misread as a topic is not a cosmetic
# loss: `heading_path` becomes `context_key` on every scar, `memory_scan` pulls
# any ticket-shaped string out of a context_key, and a context resolving to a
# CLOSED ticket makes the row `finished`, which `memory_scar_conclude` journals
# and then DELETES. One mistyped stamp is enough to bind unrelated lessons to a
# finished ticket.
#
# So the rule is now structural rather than a transcription of one writer's
# format: A HEADING WHOSE TEXT BEGINS WITH A DATE-TIME IS A WRITE-STAMP. Seconds
# and the UTC offset are optional, and a note may follow with or without a dash
# (both separators are real: session_complete writes an EM DASH, condense writes
# a HYPHEN). The lookahead stops a partial match inside a longer run of digits,
# so a malformed stamp fails this pattern loudly rather than matching half of
# itself. Misreading a genuine topic heading that opens with a timestamp costs
# only that it is filed as provenance instead of offered for tiering; misreading
# a stamp as a topic costs the binding above.
ISO_HEADING = re.compile(
    r"^(?P<hashes>#{1,6})\s+"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?)"
    r"(?=$|[\s\-–—])"
    r"\s*(?:[-–—]\s*)?(?P<note>.*)$"
)

ANY_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*)$")

# A top-level list item. Deliberately anchored at column zero: an indented dash
# is a NESTED bullet and belongs to the entry above it, not to a new one.
TOP_BULLET = re.compile(r"^[-*+]\s+(?P<text>.*)$")
NESTED_BULLET = re.compile(r"^\s+[-*+]\s+.*$")

# A blockquote or fenced block: carried verbatim inside whatever entry is open.
FENCE = re.compile(r"^\s*```")

# DWB-620: a thematic break ENDS the open section, and it is the only way the
# format can say "what follows is under no section at all".
#
# Why it had to exist. Once a write-stamp clears the chain (defect A above),
# `split` can legitimately produce an entry with an EMPTY heading_path sitting
# after a sectioned one - and `render` could not write that down. It only ever
# OPENED deeper sections: when a chain got SHORTER it emitted nothing at all and
# simply updated its own bookkeeping, so re-splitting put the entry back under
# the section that was still open. That broke `split(render(entries)) ==
# entries`, the one mechanical proof that the two halves agree.
#
# The gap PREDATES this ticket - any shortening chain hit it, ('A','B') -> ('A')
# included - and had never fired because no real file produced one. Fixing the
# splitter made the most common shortening of all, back to no section, reachable
# on every file. So this is the pre-existing hole, surfaced rather than caused.
#
# `---` is standard markdown for exactly this, it cannot be confused with a
# bullet (TOP_BULLET needs whitespace after its marker), and it appears ZERO
# times across every live memory.md measured when this landed, so nothing in the
# corpus changes meaning by its introduction.
SECTION_BREAK = re.compile(r"^-{3,}$")
SECTION_BREAK_MARKER = "---"


@dataclass
class MemoryEntry:
    """One candidate entry: the unit an agent is asked to tier, and nothing more.

    ``body`` is the lesson as written, continuation lines folded in and the
    leading bullet marker stripped. ``heading_path`` is the chain of section
    headings above it, outermost first, carried so the decide phase can show an
    entry in context without handing over the file.

    ``kind`` distinguishes a bullet from a prose paragraph because one real file
    (202 lines) has no bullets at all and is entirely prose under topic
    headings. A parser that only understood bullets would return nothing for it,
    and returning nothing looks identical to a file with no lessons.
    """

    body: str
    heading_path: tuple[str, ...] = ()
    kind: str = "bullet"  # bullet | paragraph
    # Where it came from in the source file, for a deterministic ordering and
    # for pointing a human at the original. Not part of equality: two entries
    # with the same body and heading are the same entry wherever they sat.
    line_number: int = field(default=0, compare=False)

    def __post_init__(self) -> None:
        self.body = self.body.strip()
        self.heading_path = tuple(self.heading_path)


@dataclass
class ParsedMemory:
    """Everything split() understood, kept together.

    ``provenance`` holds the ISO write-headings verbatim. They are NOT entries:
    a timestamp is not a lesson and nobody should be asked to tier one. They are
    kept rather than discarded so a caller can record what the file looked like,
    and so a round trip can put them back.

    ``preamble`` is the title and any intro prose above the first heading - the
    "# Memory - <name>" line and the paragraph explaining what the file is.
    Structure, not lessons, so it is not offered for tiering either.
    """

    entries: list[MemoryEntry] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)


def _flush_paragraph(
    buf: list[str], heading_path: tuple[str, ...], line_no: int
) -> MemoryEntry | None:
    text = "\n".join(buf).strip()
    if not text:
        return None
    return MemoryEntry(
        body=text, heading_path=heading_path, kind="paragraph", line_number=line_no
    )


def split(text: str) -> ParsedMemory:
    """Split a memory.md into candidate entries. Deterministic, no judgment.

    DWB-594 acceptance 1: running this twice on an unchanged file produces
    identical candidates. Nothing here samples, times, or randomises, and the
    entry order is source order, so that property is structural rather than
    tested-into-existence.

    A script that has to DECIDE what counts as an entry has already failed the
    snapshot phase (594's own words). So the rules are mechanical:

      * an ISO write-heading is provenance
      * any other heading opens/updates the section chain
      * a column-zero bullet starts an entry; indented bullets and unindented
        continuation lines fold into it
      * consecutive prose lines under a heading form one paragraph entry
      * a fenced block is carried verbatim into whatever entry is open
    """
    parsed = ParsedMemory()
    if not text:
        return parsed

    heading_stack: list[tuple[int, str]] = []
    # DWB-620. Both organising schemes in this repo put a write-stamp under a
    # topic heading, and they mean opposite things by it:
    #
    #   CONTAINER            APPEND-AFTER-TOPIC
    #   ## Lessons           ## Criteria, dependencies, seams
    #   ## <stamp>           - a lesson filed under that topic
    #   - a lesson           ## <stamp>
    #                        - a lesson written later, under NO topic
    #
    # Syntactically identical; the difference is whether the section had already
    # produced content when the stamp arrived. A heading whose very next element
    # is a stamp is a CONTAINER for the stamped blocks and keeps its entries. A
    # heading that already holds content is CLOSED by the stamp, because what
    # follows was appended afterwards and was not written under it.
    #
    # Clearing unconditionally was the first fix here and it is too strong: it
    # stripped the real topic off every entry in the two files that are pure
    # append logs under a heading. Never clearing is the defect. Container-ness
    # is decided once, at the FIRST stamp after a heading, and then holds for
    # that heading's whole run of stamps.
    container_mode: bool | None = None
    content_since_heading = False
    current: MemoryEntry | None = None
    para: list[str] = []
    para_line = 0
    seen_heading = False
    in_fence = False

    def close_entry() -> None:
        nonlocal current, content_since_heading
        if current is not None:
            parsed.entries.append(current)
            current = None
            content_since_heading = True

    def close_para() -> None:
        nonlocal para, para_line, content_since_heading
        if para:
            entry = _flush_paragraph(para, _path(heading_stack), para_line)
            if entry is not None:
                if seen_heading:
                    parsed.entries.append(entry)
                    content_since_heading = True
                else:
                    # Above the first heading: the file's title and its "what
                    # this file is" note. Structure, not a lesson.
                    parsed.preamble.extend(para)
            para = []
            para_line = 0

    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()

        if FENCE.match(line):
            in_fence = not in_fence
            if current is not None:
                current.body += "\n" + line
            else:
                para.append(line)
            continue
        if in_fence:
            if current is not None:
                current.body += "\n" + line
            else:
                para.append(line)
            continue

        iso = ISO_HEADING.match(line)
        if iso:
            close_entry()
            close_para()
            parsed.provenance.append(line)
            # DWB-620 DEFECT A: this branch used to `continue` without touching
            # heading_stack, and the `continue` skips the ANY_HEADING branch
            # below, which is the ONLY code that ever pops or pushes it. So the
            # last topical heading in the file survived every subsequent append
            # block and was attributed to everything written after it, forever.
            #
            # A write-stamp ENDS the section it follows. Content appended under
            # a timestamp was not written under any heading, so the correct
            # chain is empty, not inherited: an invented binding is worse than
            # no binding, because `scan_context` treats a named-but-unresolvable
            # context as `cannot_die` while an absent one takes no action.
            #
            # The two defects compounded. B injected a bogus heading onto the
            # stack and A guaranteed no valid stamp would ever clear it, so a
            # single malformed line poisoned every entry after it indefinitely.
            # Either fix alone leaves the other live, which is why they land
            # together.
            if heading_stack:
                if container_mode is None:
                    container_mode = not content_since_heading
                if not container_mode:
                    heading_stack.clear()
            continue

        heading = ANY_HEADING.match(line)
        if heading:
            close_entry()
            close_para()
            level = len(heading.group("hashes"))
            title = heading.group("text").strip()
            if level == 1 and not seen_heading:
                # The "# Memory - <name>" title line.
                parsed.preamble.append(line)
                continue
            seen_heading = True
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            # A new section: container-ness is undecided again and no content
            # has appeared under it yet.
            container_mode = None
            content_since_heading = False
            continue

        if SECTION_BREAK.match(line):
            close_entry()
            close_para()
            heading_stack.clear()
            # Structure has begun. Without this, prose that `render` placed
            # after a break would come back as PREAMBLE rather than an entry,
            # which is the one shape this format loses silently.
            seen_heading = True
            continue

        if not line.strip():
            close_entry()
            close_para()
            continue

        bullet = TOP_BULLET.match(line)
        if bullet:
            close_entry()
            close_para()
            current = MemoryEntry(
                body=bullet.group("text"),
                heading_path=_path(heading_stack),
                kind="bullet",
                line_number=i,
            )
            continue

        if current is not None:
            # A nested bullet or a wrapped continuation line. Folded in: the
            # lesson is the bullet plus everything hanging off it.
            current.body += "\n" + line
            continue

        if not para:
            para_line = i
        para.append(line)

    close_entry()
    close_para()
    return parsed


def _path(stack: list[tuple[int, str]]) -> tuple[str, ...]:
    return tuple(title for _level, title in stack)


def render(
    entries: list[MemoryEntry],
    *,
    provenance: list[str] | None = None,
    preamble: list[str] | None = None,
) -> str:
    """Render entries back to memory.md format.

    Emits entries in the order given. DWB-595 orders by tier then score before
    calling this, and that ordering is 595's business rather than the format's -
    a renderer that sorted would silently overrule its caller.

    Headings are re-emitted whenever the chain changes, so the output re-splits
    into exactly the entries that produced it. That identity is the round-trip
    test, and it is the only mechanical proof the two halves still agree.
    """
    out: list[str] = []
    for line in provenance or []:
        out.append(line)
    if preamble:
        if out:
            out.append("")
        out.extend(preamble)

    last_path: tuple[str, ...] = ()
    emitted_structure = False
    for entry in entries:
        if entry.heading_path != last_path:
            common = 0
            for a, b in zip(last_path, entry.heading_path):
                if a != b:
                    break
                common += 1

            # DWB-620. Emitting the chain from `common` onward is correct
            # whenever at least ONE heading comes out, because split pops every
            # level >= the one it sees. The broken case is the new chain being a
            # strict PREFIX of the open one: nothing is emitted, nothing is
            # popped, and the entry re-splits under a section it was not in.
            start = common
            if len(entry.heading_path) == common:
                if entry.heading_path:
                    # Re-emit the DEEPEST level of the target chain. That pops
                    # back to exactly it, and it is why a sibling move still
                    # does not re-emit a parent it already sits in.
                    start = common - 1
                else:
                    # Nothing left to emit: no heading can express "no section".
                    if out:
                        out.append("")
                    out.append(SECTION_BREAK_MARKER)
                    emitted_structure = True

            for depth in range(start, len(entry.heading_path)):
                if out:
                    out.append("")
                out.append("#" * (depth + 2) + " " + entry.heading_path[depth])
                emitted_structure = True
            last_path = entry.heading_path

        # A chainless PARAGRAPH with no structure above it re-splits as
        # preamble, not as an entry - prose before the first heading is a file's
        # title block. A break marks that structure has begun, so the paragraph
        # comes back as the entry it is. Bullets are immune: `- text` is an
        # entry wherever it sits.
        if (
            entry.kind == "paragraph"
            and not entry.heading_path
            and not emitted_structure
        ):
            if out:
                out.append("")
            out.append(SECTION_BREAK_MARKER)
            emitted_structure = True

        if out:
            out.append("")
        if entry.kind == "bullet":
            body_lines = entry.body.split("\n")
            out.append(f"- {body_lines[0]}")
            out.extend(body_lines[1:])
        else:
            out.extend(entry.body.split("\n"))

    return "\n".join(out).strip() + "\n"
