# Character persistence across shots

A character must be the same person, wardrobe, and species in every shot.

## One canonical reference per character

- Each named character maps to one actor asset and one canonical view for the whole
  film. Record this when the character's asset is approved and reuse it everywhere.
- Reuse that exact asset and view in every shot. Do not switch the chosen view
  between shots of the same character.

## Choosing the canonical view

- A face/chest-up view is strongest for facial fidelity; use it when the face
  carries the shot.
- A full-body or three-view sheet carries full-body wardrobe and proportions; use
  it when the body or outfit matters.
- Pick one canonical view per character and keep it. Mixing views across shots is a
  common source of drift.

## Never swap or merge identities

- In a multi-actor shot, bind each named actor to its own `<Picture N>`. Never
  swap, merge, or reassign actor Pictures.
- Species, face, hair, fur, wardrobe, and accessories come only from that actor's
  Picture and its approved metadata. Never invent, recolor, or add garments,
  hairstyles, colors, or accessories.
- If a character has no approved appearance description, defer to the Picture
  ("LILY, exactly as shown in `<Picture 2>`") instead of describing it.

## Wardrobe changes are explicit

- A character changes outfit only through an attached Costume reference or an
  explicit user instruction. Otherwise the canonical wardrobe carries across
  shots.
- Restate identity and wardrobe from the actor's approved metadata in the prompt so
  the model is conditioned on the same description every time.

## Re-plans and revisions

- When revising the storyboard or slot map, keep each character pinned to its
  recorded asset and view. Do not let a revision silently reassign a character to
  a similar but different asset.
