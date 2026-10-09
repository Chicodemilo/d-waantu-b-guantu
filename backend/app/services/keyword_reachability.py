# Path: app/services/keyword_reachability.py
# File: keyword_reachability.py
# Created: 2026-10-09 (DWB-667)
# Purpose: Refuse a keyword set that cannot be reached. A keyword is the term a
#          later SITUATION is matched against, so this module makes the author
#          demonstrate the match at write time, using the production matcher's
#          own predicate rather than a second copy of it.
# Caller: app/services/raw_memory.append_raw_memory (the lesson write gate),
#         app/services/memory_fill.rekey_memory (the re-keywording pass)
# Callees: app/services/memory_consult (matching_keywords, keyword_token_set,
#          _tokenize, _keyword_tokens, _MATCH_TOKENS_REQUIRED) - READ ONLY
# Data In: the author's keywords and the one-line situation they wrote
# Data Out: nothing on success; KeywordUnreachable on refusal
# Last Modified: 2026-10-09 (DWB-667)

"""The write-time half of the retrieval contract (DWB-667).

THE DEFECT THIS CLOSES, WITH ITS NUMBER. 288 live scars across five agents
carried keywords written as FILING LABELS - `self-exempt`,
`decompose-the-count`, `absence-defect`, `passes-today`, `stale-numbers`. They
name what the lesson is ABOUT. Nobody types them. Measured over a frozen set of
30 realistic situations (backend/scripts/dwb667_situations.tsv), four recalled
anything at all. The two rows that have ever fired in production carried
situational terms instead: `collation` and `git checkout`/`shared tree`.

DWB-657 already refuses a BLANK keyword. A blank keyword and an unreachable one
are the same outcome - a lesson correctly stored and never served - and only one
of them was refused, which is why 288 of them exist. A contract nobody enforces
is what produced them.

WHAT WAS SPECIFIED, AND WHY IT IS NOT WHAT IS BUILT. DWB-667 criterion 2 asked
for a corpus test: refuse a keyword whose tokens appear nowhere except the
lesson's own body. It was measured before it was rejected, against 7222
documents of inter-agent messages and ticket text:

  plain vocabulary membership   refuses 17 of 1637 live keyword tokens. No teeth.
  sentence co-occurrence        'git checkout' 123, 'shared tree' 128, but
                                'passes-today' 15, 'stale-numbers' 16,
                                'absence-defect' 9 - while 'race condition' is 0
                                and 'alembic downgrade' is 8.
  bigram adjacency              same overlap: 'passes-today' 9 beats
                                'code review' 7.

Every version needs a cut somewhere between 16 and 32 on a corpus that is
project-specific and grows, and at every cut it refuses honest keywords while
passing the ticket's own named bad ones. A tuned number is not a contract.

SO THE CORPUS IS THE AUTHOR'S OWN SENTENCE. The write carries a `situation`:
one line, in the author's words, describing the moment this lesson applies. The
keywords must MATCH it - under `memory_consult`'s predicate, not a copy of it.
That makes the gate and the retrieval path the same comparison by construction:
there is no version of this where a write passes the gate and then cannot be
recalled, because passing the gate IS being recalled, once, by a sentence the
author wrote.

No threshold, no corpus, nothing to tune, and nothing derived from the body -
DWB-654 forbids that outright and this module never reads `body` at all.

WHAT IT DOES NOT CATCH, AND WHAT COMPENSATES FOR IT. THESE ARE ONE ARGUMENT AND
THEY ARE WRITTEN TOGETHER ON PURPOSE - a limitation recorded without its control
reads as a defect nobody addressed, and a control recorded without its
limitation reads as a guarantee.

THE LIMIT. The author writes BOTH SIDES, so every keyword passes by
construction: the situation and the keyword agree on the word form because the
same person wrote them in the same minute. This does NOT require a dishonest
author writing a filing label into the situation line. An honest one, in good
faith, produces it mechanically, and the failure it hides is INFLECTION -
`grep` against "I grepped", `close` against "closing out the sprint", `trim`
against "trimming". Four agents re-keywording 290 rows hit this independently
and measured it on their own corpora: rows that cleared this gate cleanly fired
on nothing when probed with sentences written from the other end. One of them
went 6/9 on prompts written minutes after his keywords and 4/18 on fresh ones
written without looking at them - same corpus, same matcher, twice the sample, a
third of the score.

SO A GATE YOU SATISFY WITH YOUR OWN SENTENCE MEASURES REACHABILITY, NOT RECALL,
AND THE FLATTERING NUMBER ARRIVES FIRST.

THE CONTROL, which is the only thing that reaches this class: a probe set
written INDEPENDENTLY of the authors, before any of them started, by someone who
is not re-keywording, and never shown to them. backend/scripts/
dwb667_situations.tsv is that set, and backend/scripts/dwb667_coverage.tsv is
the partition that says which of its situations a corpus could even answer. No
gate can replace it, because the thing being checked is whether the author's
vocabulary matches somebody else's, and only somebody else has that.

The corollary for anyone reporting a number off this gate: a self-measured
recall rate is flattered by construction and is evidence about the FAILURE CLASS
rather than about the rate. Cite it as corroboration, never as the result.

What the gate DOES remove is the much larger class this project actually
produced: labels written without ever asking what sentence would recall them.
Nobody wrote those in bad faith; they wrote them without the question being
asked, and the question is now asked by the server, at the one moment the author
is holding the answer.

THE SECOND REFUSAL IS FREE AND CERTAIN. A keyword set whose tokens number fewer
than `_MATCH_TOKENS_REQUIRED` in total can never match any situation whatsoever
- `match_scars` already counts those rows as `unmatchable` rather than as
searched-and-not-found. Storing one is storing a lesson that is unreachable by
construction, and that is decidable at write time with no judgment at all.

IMPORTED, NOT REIMPLEMENTED, AND THE IMPORTS ARE MODULE-PRIVATE ON PURPOSE.
`_tokenize`, `_keyword_tokens` and `_MATCH_TOKENS_REQUIRED` are private names in
`memory_consult`. Reaching across for them is the lesser evil, and it is the
same call `memory_fill` already made for `_require_condensed`: a second
definition of "what counts as a token" would drift, and the drift would be
INVISIBLE, because both copies keep returning a plausible answer. One would
accept a keyword the other could never match, and nobody would see it until a
lesson failed to fire - which is a thing nobody can observe. This module
contains no tokenizer, no stopword list and no match rule of its own. If the
matcher changes, this gate changes with it, in the same commit, because it is
the same code.

MATCHING IS DONE THROUGH A KEYWORDS-ONLY STAND-IN, NOT AN `AgentMemory`.
`memory_consult`'s matching functions take a memory row rather than a list of
keywords, and the matcher must not be changed - DWB-667 forbids it in as many
words, and it is the only reason zero junk fired across 30 probes. The obvious
move is to construct a detached `AgentMemory` and pass that. It was written that
way first and DWB-637's writer guard caught it: that guard discovers every
function constructing an `AgentMemory` and requires each to resolve a clock
origin, on the grounds that a row written without one can never be scored. This
function is not a writer, but a guard that has to be told which constructors are
exempt is a guard with a hole in it, and the exemption would sit in a list of
writers where the next reader would read it as one.

So the stand-in below carries `keywords` and nothing else. It cannot be added to
a session, cannot be flushed, and cannot be mistaken for a row. If `memory_consult`
ever starts reading a second attribute, this raises AttributeError at the write
gate - loudly, at the first write - rather than silently answering a different
question.
"""

from app.services.memory_consult import (  # noqa: F401 - see module docstring
    _MATCH_TOKENS_REQUIRED,
    _keyword_tokens,
    _tokenize,
    keyword_token_set,
    matching_keywords,
)


class _KeywordsOnly:
    """What `memory_consult`'s matching functions actually read.

    `keyword_token_set` and `matching_keywords` touch `memory.keywords` and
    nothing else. This is that surface and no more of it, so the production
    predicate runs unchanged on the exact input shape while nothing here can be
    confused with, or persisted as, an `agent_memories` row.
    """

    __slots__ = ("keywords",)

    def __init__(self, keywords):
        self.keywords = keywords


class KeywordUnreachable(Exception):
    """Raised when a keyword set cannot be reached. The router maps 400.

    Its own type rather than a second `RawMemoryWriteError` code, for the same
    reason `memory_origin.MemoryOriginMissing` is its own type: the rule belongs
    to every writer of `agent_memories.keywords`, not to the one that got here
    first, and a local code would let the next writer invent a second one
    saying the same thing in different words. Both callers map it to 400.
    """

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


# A worked example is part of the message, same ruling as DWB-657's `_GOOD_BODY`.
# The caller that hits this is an agent mid-task holding a keyword set it
# believed was fine. "keywords must be reachable" names a property it cannot
# evaluate. What changes the next request is seeing a reachable one next to an
# unreachable one.
_CONTRAST = (
    "REACHABLE, because they are the words that are in the air when you are in "
    "the situation: ['git checkout', 'shared tree'], ['working tree', "
    "'mutation test'], ['sprint close', 'backlog ticket'], ['alembic', "
    "'autogenerate']. UNREACHABLE, because they name what the lesson is ABOUT: "
    "['self-exempt'], ['decompose-the-count'], ['absence-defect'], "
    "['passes-today'], ['stale-numbers']. Nobody types the second kind."
)

# The form trap, called out separately because it bites the people who are
# ALREADY writing concrete keywords. Measured on the live store: Barry_DWB's
# scars carry 'ORM model edit', 'migration proof', 'alembic downgrade' - all
# concrete, all situational, and he recalled nothing across six realistic
# situations, because the matcher does not stem and requires EVERY token of a
# keyword to be present. "I edited an ORM model" does not contain 'edit', and
# "run alembic autogenerate" does not contain 'downgrade'.
_FORM_NOTE = (
    "Every token of a keyword must be present for it to match, and nothing is "
    "stemmed: 'ORM model edit' does not match \"I edited an ORM model\". Each "
    "extra token in a keyword is another word the situation has to contain in "
    "exactly that form, so prefer two short concrete terms over one long "
    "precise one."
)


def require_situation(situation: str | None) -> None:
    """Refuse a write with no situation line.

    Refused BEFORE the keywords are judged, because without it there is nothing
    to judge them against and the author would be told its keywords are
    unreachable when the real omission is elsewhere. Same ordering rule
    DWB-657's gate settled: refuse the thing the caller can fix, in the order
    that tells it what to fix.
    """
    if situation is None or not situation.strip():
        raise KeywordUnreachable(
            "situation_required",
            "situation is required and cannot be empty. It is ONE LINE, in your "
            "own words, describing the moment this lesson applies - what you "
            "would be doing when you need it, written the way you would actually "
            "say it. Your keywords are matched against it with the SAME "
            "comparison that will later decide whether this lesson is recalled, "
            "so a keyword set that does not match your own sentence would never "
            "have been recalled by anyone's. Example: situation \"I want to undo "
            "an edit on a tree nobody has committed today\" with keywords "
            "[\"git checkout\", \"shared tree\"]. " + _CONTRAST,
        )


def require_reachable_keywords(
    keywords: list[str] | None, situation: str | None
) -> None:
    """Refuse a keyword set that this situation - or any situation - cannot reach.

    Assumes `raw_memory._require_keywords` has already refused missing, empty
    and blank lists; this adds the reachability claim on top and does not
    re-check blankness. Order is the caller's and is asserted in the tests.

    THREE REFUSALS, EACH A DIFFERENT CLAIM.

      `keyword_unmatchable` - this keyword contributes no matchable token at
      all. It is a non-string, or it is made entirely of stopwords. Nothing can
      ever match it, independent of any situation.

      `keywords_unmatchable` - the whole set contributes fewer than
      `_MATCH_TOKENS_REQUIRED` distinct tokens. `match_scars` counts such a row
      as `unmatchable`: it is not searched-and-not-found, it is incapable of
      being found. Decidable with no judgment, so it is decided here rather than
      stored and reported later.

      `keyword_unreachable` - the keyword is matchable in principle and this
      situation does not match it. This is the one the ticket is about, and the
      refusal names the specific keyword and the specific tokens the situation
      did not supply, because "unreachable" with no subject teaches nothing.

    EVERY KEYWORD MUST MATCH, not merely enough of them to clear the floor.
    Allowing two good keywords to carry a third bad one would leave exactly the
    rows this ticket exists to remove, one per write, and the author would have
    no signal that the third was dead. The guidance is two or three keywords; a
    situation sentence that contains all of them is the normal shape when they
    are situational words, and is impossible when one of them is a filing label.
    That difference is the whole gate.
    """
    terms = list(keywords or [])

    for index, keyword in enumerate(terms):
        if not _keyword_tokens(keyword):
            raise KeywordUnreachable(
                "keyword_unmatchable",
                f"keyword {keyword!r} (index {index}) carries no matchable "
                "token, so no situation can ever recall this lesson through it. "
                "It is either not a string, or made entirely of words that carry "
                "no retrieval signal on their own ('the', 'is', 'not', 'vs', "
                "'with' and so on). Write a term with a real word in it. "
                + _CONTRAST,
            )

    # The keywords-only stand-in, see the module docstring. Not a row, so it
    # cannot be added to a session and cannot be read as one by the write-site
    # guard.
    probe = _KeywordsOnly(terms)

    all_tokens = keyword_token_set(probe)
    if len(all_tokens) < _MATCH_TOKENS_REQUIRED:
        raise KeywordUnreachable(
            "keywords_unmatchable",
            f"these keywords contribute {len(all_tokens)} distinct matchable "
            f"token(s) in total and recall requires {_MATCH_TOKENS_REQUIRED}, so "
            "this lesson could never be recalled by any situation whatsoever - "
            "not a near miss, a structural impossibility. One shared ordinary "
            "word is coincidence; two distinct words co-occurring is evidence "
            "about the situation, which is why the floor is two. Either add a "
            "second term or use a two-word term that names the moment. "
            + _CONTRAST,
        )

    situation_tokens = _tokenize(situation or "")
    matched = set(matching_keywords(probe, situation_tokens))
    unreachable = [k for k in terms if k not in matched]
    if unreachable:
        missing = {
            k: sorted(_keyword_tokens(k) - situation_tokens) for k in unreachable
        }
        detail_terms = "; ".join(
            f"{k!r} needs {missing[k]} which your situation does not contain"
            for k in unreachable
        )
        raise KeywordUnreachable(
            "keyword_unreachable",
            f"your own situation does not recall {len(unreachable)} of your "
            f"keywords: {detail_terms}. A keyword is not a label for what the "
            "lesson is ABOUT - it is the term a future situation is matched "
            "against, with the same comparison used here. If the sentence you "
            "just wrote about this moment does not contain the word, no "
            "sentence anyone writes later will either, and the lesson will be "
            "stored correctly and never served. Either rewrite the keyword in "
            "the words you actually used, or widen the situation if it was too "
            f"narrow. {_FORM_NOTE} {_CONTRAST}",
        )


# ---------------------------------------------------------------------------
# DWB-669: THE KEYWORD THAT FIRES WITHOUT ITS SUBJECT.
# ---------------------------------------------------------------------------
#
# WHAT WENT WRONG, WITH ITS NUMBER. DWB-667's contract told authors to widen
# their keyword sets, and widening is close to free EXCEPT for one shape: a
# multi-token keyword made entirely of ordinary non-subject words. It clears
# `_MATCH_TOKENS_REQUIRED` BY ITSELF, so it needs no help from any other keyword,
# and it fires on any sentence that happens to contain the phrase. Measured over
# 20 negative controls drawn from this project's own vocabulary: `before i` fired
# on "the epic needs a description before I create it", `show me` on "show me the
# activity feed", `every agent` on "list every agent assigned to project 1".
#
# TWO CONDITIONS, AND BOTH ARE LOAD-BEARING.
#
#   1. The keyword clears the floor ALONE - it contributes at least
#      `_MATCH_TOKENS_REQUIRED` distinct tokens by itself. A keyword below that
#      cannot fire without a second keyword agreeing with the same situation, so
#      it is not this defect.
#   2. EVERY one of its tokens is in `_NON_SUBJECT_TOKENS` below.
#
# CONDITION 1 ALONE WOULD DELETE THE WORKING CORPUS, and that is not a theory -
# it was proposed and it is true of `git checkout`, `shared tree`, `sprint close`
# and every other two-word keyword that has ever fired correctly here. Condition 2
# is what separates `hand over` from `git checkout`. Condition 1 is the right
# FRAME - the defect is a keyword that fires with no help - and the list is what
# makes it decidable.
#
# A CLOSED HAND-WRITTEN LIST, NOT A CORPUS FREQUENCY CUT, AND THAT IS SETTLED BY
# MEASUREMENT RATHER THAN TASTE. DWB-667 measured three frequency-shaped rules
# against 7222 documents of this project's own text and none of them separates the
# named good examples from the named bad ones: plain vocabulary membership refuses
# 17 of 1637 live tokens; sentence co-occurrence scores 'git checkout' 123 and
# 'shared tree' 128 but 'passes-today' 15 and 'alembic downgrade' 8; bigram
# adjacency has the same overlap. Every cut needs a threshold tuned on a corpus
# that grows. This list is the same shape as `memory_consult._SITUATION_STOPWORDS`
# - short, named, and arguable one entry at a time - which is the only form that
# can be audited by a person.
#
# WHAT IS NOT IN HERE, DELIBERATELY. `column`, `checkout`, `alembic`, `tree`,
# `sprint`, `downgrade`, `edit`, `grep`, `collation`. Those name a THING. The test
# that decides membership is: could this word appear in a sentence about any part
# of this project at all? `file`, `code`, `agent`, `write`, `line` and `check` can,
# which is exactly why they carry no retrieval signal when paired with each other.
#
# `new column` MUST PASS AND `new file` MUST REFUSE, and that pair is the sharpest
# test of the cut. `new` is in the list and `column` is not, so `new column`
# survives on its subject word. If a future edit puts `column` in here, the rule
# has become too wide and this comment is the evidence that it was once right.
#
# `before i edit` MUST PASS. It clears the floor alone and two of its three tokens
# are in the list, but `edit` is not, so it carries a subject. A rule that refuses
# it is wrong, not the keyword.
#
# THE FLOOR DOES NOT MOVE AND THE COMPARISON DOES NOT CHANGE. DWB-644 settled that
# raising `_MATCH_TOKENS_REQUIRED` narrows coincidence and real recall identically,
# and DWB-669 does not reopen it. This rule removes a route; it does not retune a
# measurement.
#
# THIS RULE IS NOT ENFORCEABLE BY DWB-667'S GATE AND HAD TO BE ITS OWN CHECK.
# 667 asks only whether a keyword appears in the author's situation line, and a
# subject-free pair appears there BY CONSTRUCTION - the author who writes
# `another agent` writes "another agent" in the sentence beside it, honestly,
# because the lesson genuinely is about another agent. 667 cannot separate "this
# phrase names my subject" from "this phrase is two ordinary words"; that
# distinction is the whole of this rule, which is why it is a separate predicate
# running BEFORE 667's rather than a tightening of it.
#
# AND THE DEFECT PREDATES THE WIDENING THAT MADE IT COMMON. Four of the first
# sweep's terms - `found nothing`, `never ran`, `read the code`, `line range` -
# were written before any widening instruction existed, and `never ran` cleared
# 667's gate on the day it was written. The hole was in the gate from the start;
# widening raised its frequency. The story is not "the remedy opened a channel".
#
# THE BARE GENERIC SINGLE WORD IS NOT ENFORCED HERE, and that is an answer rather
# than an omission. The measurement behind it: 64 single-token keywords whose one
# token is in the list below, across 292 rows, and only 7 rows of 595 can fire on
# bare generics ALONE. Banning them costs one situation on the frozen 30, and it
# would refuse `collation`, `grep` and `alembic`, which are single words that are
# exactly right.
#
# THE SECOND HALF OF THAT MEASUREMENT HAS SINCE BEEN FALSIFIED AND IS CORRECTED
# HERE RATHER THAN QUIETLY LEFT. It used to read "real in principle, fired nothing
# in practice", on zero bare-generic pair fires across 100 agent-by-control pairs.
# An agent then produced one: a draft row carrying `check` beside `population`,
# fired by "check the population of the staging database". Two ordinary words, no
# subject in either, pairing exactly as the channel predicts. Neither gate refuses
# it - `check` is a single token so it never clears the floor alone, which is the
# condition this rule turns on, and 667 agrees because the author's own situation
# contains both words.
#
# The DECISION stands on the cost, not on the absence: one observed instance
# against zero in a hundred pairs is not a reversal, and the cure refuses good
# single words. What has changed is that it is no longer defended by "we saw
# none". ABSENCE ON A CONTROL SET IS NOT ABSENCE, and the control set was mine.
_NON_SUBJECT_TOKENS = frozenset(
    {
        # From the refusal set these were derived from: every token of every
        # keyword that was demonstrated firing on a real unrelated sentence.
        "agent", "agents", "all", "already", "answer", "before", "both", "case",
        "check", "code", "common", "correct", "current", "double", "down",
        "every", "file", "files", "found", "gets", "ground", "hand", "i", "its",
        "left", "line", "me", "never", "new", "nothing", "now", "off", "one",
        "output", "over", "own", "prose", "ran", "range", "read", "result",
        "right", "same", "scan", "second", "served", "shape", "shot", "show",
        "sign", "taken", "truth", "twice", "two", "up", "us", "what", "write",
        "writing",
        # Named by an author as obvious siblings, each demonstrated or argued
        # individually rather than added as a family: 'how many', 'go and look',
        # 'still true'.
        "how", "many", "go", "look", "still", "true",
        # DWB-669, added on the SAME evidence standard as everything above and
        # not on a hunch: `another agent` was a demonstrated false fire in the
        # frozen-30 measurement, recalling a lesson about reading a guard's
        # refusal text on the situation "I am writing a section that contradicts
        # something another agent published an hour ago". It is the same shape as
        # `every agent` and `all agents`, which were already here.
        #
        # ITS BLAST RADIUS WAS CHECKED BEFORE IT WENT IN, over every live keyword
        # containing it: 'another agent' x3 refuse, and 'another tool',
        # 'another project', 'another field' and 'another process' all survive on
        # their subject noun. A word that refused those too would be too wide.
        "another",
        # DWB-669 second pass. A worker found the rule INCONSISTENT WITHIN A ROW:
        # #1362 was told to drop `one-shot` and kept `what does it mean`, and
        # #566 kept `looks fine`. Same class, left behind, so the row read as
        # SWEPT while still firing - which is worse than never sweeping it,
        # because the next reader believes it was checked. Each of these is a
        # demonstrated fire: `what does it mean` on "what does it mean that the
        # build is slow", `looks fine` on "I ran it and the result looks fine".
        #
        # THE HUNT FOR THEM WAS MECHANICAL AND THE REST OF IT WAS REFUSED. Every
        # multi-token keyword ONE token away from refusal was enumerated; the
        # word that would close each one is mostly a real subject - `memory`,
        # `number`, `path`, `column`, `tool`, `field`, `function` - and adding
        # those would be the too-wide failure this list is watched for. Only
        # words with an observed fire went in.
        "does", "mean", "means", "looks", "fine",
        # `after`, and the way it got here is worth the three lines.
        #
        # The author of this rule wrote `before and after` as a keyword on his own
        # memory row, in the session he named this class, then told the lead TWICE
        # that "the rule refuses it" - having never run it. It does not: `before`
        # was in the list and `after` was not. The row was cleaned because the lead
        # ruled it should be, not because the rule caught it, and the sweep was
        # reporting zero offenders store-wide while the keyword sat live on another
        # project.
        #
        # That is a conclusion asserted from a NAME with no artifact behind it,
        # inside the ticket written to stop exactly that, by the person who wrote
        # the refusal message about it. The fix is one word; the reason it is
        # recorded here is that nothing else would have caught it - the tests pass
        # either way, because a rule's test suite only contains the cases someone
        # thought to write down.
        #
        # Blast radius checked first, over every live keyword containing `after` or
        # `before`: exactly ONE refusal store-wide, `before and after` on IND #939.
        # `after their`, `after my change`, `re-profile after fix`, `before i edit`,
        # `before filing`, `before deleting` all survive on their subject word.
        "after",
        # Inflections of words ALREADY above. The matcher does not stem, so an
        # author writing the other form would otherwise walk straight through a
        # rule the singular already covers. Nothing is added here whose base form
        # is not in the list above.
        "answers", "cases", "checks", "lines", "outputs", "reads", "results",
        "scans", "shapes", "shows", "writes",
    }
)


def fires_without_subject(keyword: str) -> bool:
    """Does this keyword clear the match floor on its own with no subject in it.

    Both DWB-669 conditions, in the order that makes the cheap one first. Pure,
    importable, and used by the sweep as well as the gate, so the list that
    refuses a write is the same list that produces the cleanup.
    """
    tokens = _keyword_tokens(keyword)
    if len(tokens) < _MATCH_TOKENS_REQUIRED:
        return False
    return tokens <= _NON_SUBJECT_TOKENS


def require_subject_bearing_keywords(keywords: list[str] | None) -> None:
    """Refuse a keyword that fires on ordinary prose with no subject in it.

    Independent of the situation line ON PURPOSE. A junk keyword that happens to
    appear in the author's own situation would sail through the DWB-667 check -
    in fact it is MORE likely to, because an author who wrote `before i` will
    have written "before I" in the sentence beside it. The two rules answer
    different questions and neither covers the other.
    """
    for index, keyword in enumerate(keywords or []):
        if not isinstance(keyword, str) or not fires_without_subject(keyword):
            continue
        raise KeywordUnreachable(
            "keyword_fires_without_subject",
            f"keyword {keyword!r} (index {index}) is made entirely of ordinary "
            "words that name no subject, and it carries enough tokens to be "
            "recalled ON ITS OWN. That means it fires on ANY sentence containing "
            f"the phrase {keyword!r}, whatever that sentence is about - measured: "
            "'before i' fired on \"the epic needs a description before I create "
            "it\", 'show me' on \"show me the activity feed\", 'every agent' on "
            "\"list every agent assigned to project 1\". A lesson recalled by an "
            "unrelated sentence is worse than one never recalled: it reaches an "
            "agent who is not in that situation, and at the promotion threshold a "
            "coincidence becomes permanent. Put the SUBJECT in it. 'before i' is "
            "refused and 'before i edit' is accepted, because `edit` names the "
            "thing; 'new file' is refused and 'new column' is accepted, for the "
            "same reason. Widening your set is still right - this is the one "
            "widening that is not free, and declining to ADD a junk route is not "
            "narrowing.",
        )
