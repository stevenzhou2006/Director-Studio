# H3 prompt writing

## Bind real conditioning

Bind every active Layout to its real `<Picture N>` and name the geography, blocking, or object state it adds. Treat all Pictures as whole-clip conditioning; timing belongs only in `detailed_description`. Multiple Layouts may describe compatible states within one continuous beat, but never claim that one activates at a timestamp. A continuity / tail-frame Layout is an ordinary Picture: never call it a first frame, last-frame socket, or an image that activates only at the beginning. It may preserve blocking, wardrobe, and geography carried from a prior shot.

## Lock actor identity and wardrobe

Each actor reference carries an `asset_name` and a `picture_index`. Bind every named actor to that actor's own `<Picture N>` exactly, and never swap, merge, or reassign actor Pictures, even when a shot holds two or more actors. Species, face, hair, fur, wardrobe, and accessories come only from the actor Picture and its approved metadata. Never invent, recolor, or add garments, hairstyles, colors, or accessories, and never carry wardrobe, hair, or color claims out of a Layout's `visual_analysis` — that analysis covers composition, blocking, and lighting only. If no approved appearance description exists, defer to the Picture instead of describing it, for example "LILY, exactly as shown in `<Picture 2>`".

## Write one feasible clip

Preserve exact dialogue once, keep every timing interval within `duration_s`, and state required non-appearance positively. Use approved metadata and describe motion directly without assigning Pictures to time windows.

## Escalate incompatible reveals

Recommend splitting when early leakage of a subject or object would invalidate the shot. Do not pretend that Picture ordering can conceal a state from the rest of the clip.

## Retention analysis markers

`retention_analysis` is not freeform prose. Give one line per reference label, in the order the labels appear in `subject_definitions`, using a fixed marker followed by a short justification:

```text
<Picture N> (<role it plays>): <marker> - <what is kept, changed, or transferred>
<Audio N>: <marker> - <what is kept, changed, or referenced>
```

Visible labels (`<Picture N>`) use exactly one of:

- `fully_preserved` — the role defined for that Picture is carried through intact (identity, geography, blocking, or style as scoped).
- `partially_preserved` — the Picture is still used but some defined characteristics change or are only partly retained.
- `attribute_transfer` — a referenced characteristic moves onto a different identified subject (e.g. a wardrobe or lighting cue carried from one reference onto another actor).
- `weak_reference` — only broad similarity in style, category, composition, or atmosphere is retained.

Audio labels (`<Audio N>`) use exactly one of:

- `fully_copy` — the complete source signal is the target clip's audio.
- `partially_copy` — part of the timeline or selected layers are copied, or sounds are added/removed/replaced after copying.
- `reference` — the signal is not copied; only timbre, rhythm, delivery, or accent guides the new performance.
- `weak_reference` — only broad category or atmosphere similarity is retained.

Pick each marker only within the role already assigned to that label in `subject_definitions`; do not treat newly added action, background, or story events as a loss of reference fidelity. A Director poem shot that binds a recitation voice typically reads `<Audio 1>: reference - the recitation follows <Audio 1>'s timbre and measured delivery without copying the original signal.`, and a Layout that locks the courtyard reads `<Picture 3> (courtyard geography and light): fully_preserved - the same plate, landmarks, and light direction carry through the whole clip.`

## Recitation is on-screen speech with lip-sync

A shot with a poem recitation or dialogue is the ON-SCREEN character speaking, not a
narrator. The reciting character (for the cat-poet series, DALI) must be shown actually
vocalizing: mouth, jaw, lips, and breath moving in sync with `<Audio N>` and the words.

- In `subject_definitions`, bind the voice to the speaking character as their own voice,
  e.g. `DALI recites the poem in <Audio 1>; his mouth and jaw move in sync with the
  recitation.` Do NOT write it as a separate off-screen teller ("a young girl's voice
  recites over the scene", "narration", "voice-over").
- In `detailed_description`, describe the speaking beat concretely and time it to the
  audio: which character speaks, when their mouth opens/closes, head/eye posture while
  reciting, and that the movement tracks `<Audio N>`'s delivery.
- The voice's timbre (child, dialect, stylized) belongs to the on-screen speaker. A
  closed or unmoving mouth on a shot that carries a recitation is a defect — the cat must
  visibly be the one reciting.
- The non-speaking character still reacts (see reaction rule), but only the named speaker
  has synced mouth movement.
- **Mouth visibility is mandatory.** The speaker's face and mouth must be in clear view of
  the camera (front or three-quarter/profile) for the whole spoken line. Do NOT pick a
  composition that hides the mouth during the recitation: no top-down / high-angle-into-a-
  basket-or-object view, no head lowered or turned away, no muzzle buried in food/prop, no
  back-of-head framing while the line is spoken. If the action has the cat looking down or
  handling a prop, have it lift its head to face the camera to recite, and place the
  down-look/prop business before or after the spoken line. A recitation with the speaker's
  mouth hidden cannot lip-sync — this is the single most common cause of a "not lip-synced"
  shot.

## Describe, do not summarize

`detailed_description` is the conditioning payload, not a synopsis. For each shot state, make it explicit and observable: composition and framing, each subject's appearance and position, environment and lighting, the action and any state change, camera movement (type, amplitude, speed when it matters), the sound present in the moment, and exactly where each referenced `<Picture N>` / `<Audio N>` takes effect. Avoid reducing it to a plot summary or a list of reference relationships.

Prefer concrete, visible detail over empty adjectives: "cinematic", "beautiful", "stunning", "epic" carry no conditioning and are banned as substitutes for description. Scale length to the clip — these are short whole-clip generations (a few seconds per poem line), so aim for one tight, information-dense paragraph per shot rather than a fixed word target; never pad to reach a count.

## Summary task-type prefix

Open `summary` with one bracketed task-type tag, then a single short paragraph that reuses only the labels already defined in `subject_definitions` (introduce no new labels there):

- `[reference generation]` — Pictures guide character, scene, style, action, or composition without being a copied frame anchor.
- Add `+ audio reference` when a voice `<Audio N>` conditions delivery/timbre without copying the signal.
- Add `+ audio reuse` only when the exact audio signal is reused in full or in part.

A typical Director poem shot reads `[reference generation + audio reference]`.

## Cross-section label consistency

A label assigned in `subject_definitions` keeps the same meaning in `summary`, `retention_analysis`, `detailed_description`, and the audio sections. Do not redefine, renumber, or drop a label mid-prompt, and do not reference a `<Picture N>` or `<Audio N>` that was not submitted.

## Name the camera move concretely

Describe camera work with a specific movement, amplitude, and speed rather than a vague "cinematic shot". Use the standard vocabulary and combine it when the move is compound:

- **Dolly in / dolly out** — the camera physically pushes toward or pulls back from the subject (changes perspective, not just framing).
- **Truck left / truck right** — the camera travels laterally, parallel to the plane.
- **Pan left / pan right** — the camera rotates horizontally on a fixed pivot.
- **Tilt up / tilt down** — the camera rotates vertically on a fixed pivot.
- **Pedestal up / down** — the whole camera rises or lowers vertically.
- **Orbit** — a circular move around the subject; state it as a compound `truck left + pan right` (or the reverse) so the model reads both the travel and the rotation.
- **Handheld** — a breathing, slightly unstable frame; say how much shake (subtle vs pronounced).
- **Over-the-shoulder (OTS)** — frame past one subject's shoulder or head onto the other.
- **Crane / jib** — a vertical sweeping move that also reveals scale.

Tie the move to the beat: a slow dolly-in for a growing realization, a held locked-off frame for a deadpan line, a quick pan to follow a turn. Do not stack multiple large moves in one short shot.

## Make the listener react

In any shot with more than one subject, the non-speaking subject must show a concrete, visible reaction to the specific line just heard — an eye shift, a held breath, a jaw tightening, a small step, a hand curling — not a generic "listening carefully" or "watching". Reaction is what sells a dialogue exchange; an inert listener reads as a still image.

## Pin the end-frame state

Close `detailed_description` on an explicit final state so the next shot can continue from it or QC can verify continuity: each subject's position, posture, and gaze; distance and any contact between them; held props and their state and location; camera framing and light direction. Do not let a subject, a held object, or a contact vanish or teleport between the described end state and the next shot's opening.

<!--
source: MiniMax-AI/MiniMax-H3 skills/h3-prompt-writing (references/ref-en.txt)
pinned commit: d21241f0a4b3acbb34c97dae47fa417b7065e438 (2026-08-15)
Adapted for Director Studio: whole-clip Ref2AV only. The upstream <Subject N>
abstraction, <d>[lang]</d> dialogue tags, (Sx) speaker IDs, and
[Shot N] At MM:SS.mmm timing are intentionally NOT adopted here — the H3
prompt builder validates only <Picture N>/<Audio N> indices and the Director
doctrine forbids per-shot timeline/keyframe claims. Re-sync the marker
vocabulary and detail guidance from the pinned guide when upstream changes.
-->
