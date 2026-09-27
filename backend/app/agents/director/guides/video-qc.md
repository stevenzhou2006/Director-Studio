# Video QC

## Check the actual clip

Review identity, continuity, composition, action timing, dialogue, prop state, early subject or object leakage, and contradictions among active Layouts and other Picture references. Inspect representative early, middle, and late frames alongside audio and metadata.

## Diagnose before repair

Separate a prompt or model failure from a source-reference failure. Record the observed evidence before recommending a repair, so the next attempt changes the right cause.

## Decide usability

Classify the clip as usable, usable with trim, or reject based on the completed output rather than job status alone.

## Pacing, transition, and end-state checks

- **Speech fits the duration.** The spoken or recited content lands inside the clip at a natural pace — no rushed, clipped, or trailing-off delivery, and no dead air from an under-filled unit.
- **One action chain.** The clip carries a single start-response-result chain, not two unrelated ones competing for the seconds.
- **Boundary type is honored.** A continuous split opens with a visible carryover of the prior motion and lines up in momentum, camera, and pose; an independent cut is a clean new framing.
- **End-state is stable.** Subjects, held props, contact, and light are consistent at the final frame with what the next shot expects or with the scene's locked geography.
- **No unintended text or music.** No on-screen text, watermark, or logo appears unless intended, and background music is present only when the brief asked for it.
