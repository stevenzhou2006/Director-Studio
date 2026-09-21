# Character persistence across shots

A character must be the same person, wardrobe, and species in every shot. The
project continuity anchor is the mechanism that guarantees this.

## One canonical reference per character

- Each named character maps to one actor asset and one canonical `file_key` for the
  whole project. The continuity anchor records this on the first plan.
- Reuse that exact asset and view in every shot. Do not switch `file_key` between
  shots of the same character.

## Choosing the canonical view

- `bust_threeview` is strongest for facial fidelity; use it when the face carries
  the shot.
- `fullbody_threeview` or `master` carries full-body wardrobe and proportions; use
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
  explicit user instruction. Otherwise the canonical wardrobe carries across shots.
- Restate identity and wardrobe from the actor's approved metadata in the prompt so
  the model is conditioned on the same description every time.

## Re-plans and recasts

- When re-planning or recasting, the anchor re-pins each character to its recorded
  asset and view. Do not let a re-plan silently reassign a character to a similar
  but different asset.
