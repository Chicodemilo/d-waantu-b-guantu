// Path: src/components/project/MemoryTransitionOverlay.jsx
// File: MemoryTransitionOverlay.jsx
// Created: 2026-09-30
// Purpose: DWB-597 status strip shown while a project is mid memory-mode transition. Reads DWB-596's derived status and renders one line saying what is cooking and how far along it is. It computes no progress of its own and it never blocks the page.
// Caller: src/pages/ProjectPage.jsx
// Callees: react (useState, useEffect), ../../api/projects (getMemoryTransition)
// Data In: project (for id and memory_mode), lastPolled (to re-read on the master poll tick)
// Data Out: Default export MemoryTransitionOverlay component
// Last Modified: 2026-09-30 (DWB-597: a run that wrote nothing must not read as success)

import { useEffect, useState } from 'react';
import { getMemoryTransition } from '../../api/projects';

// The two states that mean a transition is running. A project outside them has
// no transition to show, and per DWB-596 that question is answered by
// memory_mode alone: we must not call the endpoint to find out something we
// already know, and must never render a zeroed strip for a project that never
// started one.
const TRANSITION_MODES = ['adopting', 'reverting'];

const DIRECTION_LABEL = {
  adopt: 'Adopting',
  revert: 'Reverting',
};

// Called ONLY with a run that exists, so there is no absent-run branch here.
// The endpoint returns an explicit `status`, so nothing here re-derives one.
// DWB-596 gives every "empty" case its own value precisely so a consumer does
// not have to infer from a count or a null timestamp, and a consumer that
// infers anyway rebuilds the ambiguity the producer just removed. These are
// the only values that render; anything else means the project has no
// transition worth showing.
const RUNNING = 'in_progress';
const READY = 'complete';
// An open run whose entries were never enumerated. Enumeration is atomic with
// the BEGIN request, so this cannot happen in normal operation: seeing it means
// a partial transaction, a hand-edited row, or corruption.
//
// IT IS AN ERROR, NOT A PHASE (TL ruling). The obvious rendering, "preparing
// entries", is wrong precisely because it is reassuring: it tells the reader
// something is cooking when nothing is, so they wait instead of reporting it.
const BROKEN = 'not_enumerated';

function describe(run) {
  const what = DIRECTION_LABEL[run.direction];
  if (!what) return null;

  if (run.status === READY) {
    // DONE IS NOT THE SAME AS LANDED. written, journaled and skipped are all
    // terminal, so a run where every entry was skipped is legitimately
    // complete and has moved NOTHING into the new store. Reporting that as
    // "all 51 entries done, ready to cut over" invites someone to confirm a
    // cutover into an empty store, which is the outage this whole lane exists
    // to prevent, arriving through the display instead of through the guard.
    //
    // Skipping everything is a legitimate choice and is NOT blocked. It just
    // must not read as a successful migration.
    if (run.entries_total > 0 && run.entries_written === 0) {
      return null;
    }
    const landed = `${run.entries_written} of ${run.entries_total} written`;
    return `${what}, ${landed}, ready to cut over`;
  }
  if (run.status !== RUNNING) return null;
  return (
    `${what}, ${run.entries_done} of ${run.entries_total} entries, ` +
    `${run.agents_done} of ${run.agents_total} agents done`
  );
}

function MemoryTransitionOverlay({ project, lastPolled }) {
  const [run, setRun] = useState(null);
  const [failure, setFailure] = useState(null);

  const projectId = project?.id;
  const inTransition = TRANSITION_MODES.includes(project?.memory_mode);

  useEffect(() => {
    if (!inTransition || !projectId) {
      setRun(null);
      setFailure(null);
      return undefined;
    }
    const controller = new AbortController();
    getMemoryTransition(projectId, { signal: controller.signal })
      .then((data) => {
        // `state` is the RUN's state and is null when there is no open
        // run, which is how not_started and idle arrive. Keyed on it rather
        // than on status so a value added to that enum later cannot make this
        // render something it has no sentence for.
        setRun(data && data.state ? data : null);
        setFailure(null);
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        // A transition IS running and we cannot say how far along. Saying so
        // beats rendering nothing, which is indistinguishable from no
        // transition at all.
        setRun(null);
        setFailure(err.message || 'Could not read the transition status.');
      });
    return () => controller.abort();
  }, [inTransition, projectId, lastPolled]);

  // The render-time `!inTransition` guard that used to sit here is GONE, and
  // this note is the receipt. The argument for it was that effects run after
  // paint, so a poll flipping memory_mode back would leave the previous run in
  // state for one painted frame and the strip would claim a finished
  // transition was still running. Plausible, and wrong.
  //
  // MEASURED IN A REAL BROWSER with the guard removed: an rAF sampler recorded
  // 721 frames across a live mode flip, correlating the strip against the mode
  // the page was rendering from the same prop. It saw both modes, so the flip
  // really happened, and ZERO frames showed the strip after the mode had moved
  // on. React batches the update and the effect closely enough that the
  // inconsistent frame is never painted.
  //
  // Clearing `run` in the effect is therefore sufficient, and the guard was
  // defending against something that does not occur. It had a deadline in this
  // comment precisely so it could not survive on the strength of the argument
  // alone; the deadline is what settled it, not the reasoning.

  if (failure) {
    return (
      <div className="memory-transition memory-transition--failed">
        A memory-mode transition is running on this project, but its status
        could not be read. {failure}
      </div>
    );
  }

  // Complete, and nothing reached the new store. Rendered where the ordinary
  // status would have been, in the failure style, because the reader is about
  // to decide whether to confirm a cutover and the ordinary sentence would
  // tell them it worked.
  if (
    run
    && run.status === READY
    && run.entries_total > 0
    && run.entries_written === 0
  ) {
    return (
      <div className="memory-transition memory-transition--failed">
        Every one of the {run.entries_total} entries finished without being
        written to the new store
        {run.entries_skipped > 0 ? `, ${run.entries_skipped} skipped` : ''}
        {run.entries_journaled > 0 ? `, ${run.entries_journaled} journaled` : ''}
        . Cutting over now would leave this project with an empty memory store.
        Check that this is what was intended before confirming.
      </div>
    );
  }

  if (run && run.status === BROKEN) {
    return (
      <div className="memory-transition memory-transition--failed">
        This project is mid transition but its entries were never enumerated.
        That is not a stage of the process, it means the transition did not
        start correctly. Report it rather than waiting for it to finish.
      </div>
    );
  }

  const line = run ? describe(run) : null;
  if (!line) return null;

  return <div className="memory-transition">{line}</div>;
}

export default MemoryTransitionOverlay;
