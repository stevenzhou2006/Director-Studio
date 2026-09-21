# Director Studio JSON Production Contract

Read this only after the script, storyboard, assets, and per-shot slot maps are
approved and the user explicitly requests final JSON.

Return one valid JSON object with no Markdown fence or surrounding explanation.

## Document

```json
{
  "version": 1,
  "revision": 0,
  "aspect_ratio": "16:9",
  "shots": []
}
```

- `version` must be `1`.
- `revision` must be an integer `>= 0`; use `0` for a new import.
- `aspect_ratio` must be `"16:9"` or `"9:16"`.
- Shot IDs must be non-empty and unique.

## Shot

```json
{
  "id": "shot_001",
  "title": "Corridor entry",
  "script_beat": "Lu enters the archive and senses that she is being watched.",
  "duration_s": 6,
  "dialogue": [],
  "pictures": [
    {
      "index": 1,
      "role": "actor",
      "label": "Approved Lu identity and navy wardrobe reference"
    }
  ],
  "audio": [],
  "prompt": {
    "subject_definitions": "<Picture 1> defines Lu's approved identity and wardrobe.",
    "summary": "A six-second reference-guided corridor entrance.",
    "retention_analysis": "Preserve Lu's identity, navy wardrobe, and restrained performance.",
    "detailed_description": "0-6 seconds: Lu enters the corridor, slows, and stops beside the archive desk as the camera makes a restrained forward push.",
    "overall_soundscape": "Quiet rain outside and a steady fluorescent hum.",
    "non_diegetic_music": "No non-diegetic music."
  }
}
```

## Field Rules

- `title` is non-empty.
- `script_beat` is a string and may be empty.
- `duration_s` is a number `> 0` and `<= 15`.
- `dialogue` is an array of strings. Preserve approved lines exactly.
- `pictures` contains 1-9 objects. Indices must be ordered and contiguous from 1.
- Picture `role` is one of `actor`, `costume`, `scene`, `prop`, `layout`, `other`.
- `audio` contains 0-3 objects. Indices must be ordered and contiguous from 1.
- Every `label` is non-empty and identifies the exact approved asset the user
  should attach; it is not an invented path or ID.
- A slot may optionally carry `asset_id` and `file_key` to link it to a real
  Director Studio library asset. When `asset_id` is present, Director Studio
  resolves that slot's bytes from the library and the label is the human-readable
  name of the linked asset. When it is absent, the slot is filled by a manual
  upload in Director Studio. Do not invent `asset_id` values; use one only when it
  is an ID you were actually given.
- All six `prompt` values are non-empty strings.

## Final Validation

First enforce the exact document shape shown above. Reject generic lookalike
schemas that add a `project` wrapper, use `duration_sec` instead of `duration_s`,
use Picture fields such as `type`, `src`, or `character_reference`, or provide
`prompt` as one string instead of the six-field object. Reject invented `ref://`
URIs, ungenerated tail frames, filenames, IDs, or asset approvals.

Every Picture and Audio label must name a real user-provided or user-approved
asset that actually exists in the production. A label is an authoring declaration,
not a runtime guarantee: only `asset_id` links a slot to a library asset, and
Director Studio verifies that link when the shot is submitted. Do not invent
`asset_id` values or claim that a label resolves when it does not.

Before formatting the final object, confirm that every shot's requested actions,
camera changes, dialogue, and state transitions can plausibly fit its duration.
Split or revise an overloaded shot rather than exporting an internally valid but
unproducible instruction.

Across all six prompt fields:

- every declared Picture index appears as `<Picture N>`;
- every declared Audio index appears as `<Audio N>`;
- no undeclared Picture or Audio tag appears;
- no Picture is assigned a start, middle, end, or activation time;
- no timed clause contains a Picture/Layout tag or says that a reference controls
  a timed state; whole-clip bindings and action timing are separate sentences;
- all action timing fits `duration_s`;
- every string in `dialogue` appears exactly once, unchanged;
- JSON contains no comments, trailing commas, placeholders, or extra prose.
