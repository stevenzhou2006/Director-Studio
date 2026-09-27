# Shot transitions and continuity handoff

## Decide the boundary type first

Every join between two consecutive shots is one of two kinds. Classify it before
generating, because the kind determines whether a tail-frame reference is needed
and how the opening action must be written.

### Continuous split

The two shots are really one unfinished shot cut apart by the 15-second generation
limit — a connected action sliced mid-motion, or a one-take camera move that
crosses the boundary. The end of the earlier shot and the start of the later shot
must line up in momentum, camera position, and body pose.

- Use a tail-frame Layout: extract the last frame of the earlier clip
  (`extract_clip_tail_frame`) and attach it as the later shot's continuity Picture.
- In `detailed_description`, the first action interval must open at 0 seconds with
  a visible carryover that continues the prior motion (the pipeline's tail-frame
  transition check enforces this).
- Do not write a hard cut, a style-only cue, or a hidden source state across a
  continuous boundary — that breaks the seam.

### Independent cut

The boundary is a deliberate new shot: a different framing, angle, or scene. No
tail-frame guidance is required; a clean hard cut is correct and expected.

## Record the decision

For each boundary, note which kind it is and why (e.g. "same grab-and-struggle
action split at 15s ⇒ continuous" versus "new close-up on a different axis ⇒
independent cut"). This is the reason the next shot's reference pack is built the
way it is.

## End-frame state

The last shot of a unit must pin down the final visible state so the next unit can
reset from it (continuous) or so continuity can be verified (independent):

- each subject's position, posture, and gaze;
- distance and any contact between subjects;
- held props and their state and location;
- camera framing and light direction.

Carry that exact state into the opening of the next unit when the boundary is
continuous. When it is an independent cut, the new unit re-establishes blocking
for its own framing but must not silently contradict the prior scene's geography or
light.

## Whole-clip doctrine reminder

A tail-frame Layout is an ordinary Picture that conditions the entire clip. Calling
a boundary "continuous" governs the action prose and the choice of reference; it
does not make the Picture a time-addressable keyframe and does not give it a start
or end role. Never claim the reference "activates at" a timestamp.

<!--
source: MiniMax H3 导演台 inter-segment guidance (continuous-vs-cut boundary),
adapted to Director Studio's tail-frame extraction flow and whole-clip Ref2AV
doctrine.
-->
