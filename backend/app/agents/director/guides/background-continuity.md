# Background persistence across shots

The room must read as the same room in every shot that takes place in it. Background
drift is one of the most visible continuity failures.

## Always attach the scene reference

- Every shot in an established location includes the approved Scene reference as a
  Picture. Do not rely on prose alone to hold the room.
- Bind the scene `<Picture N>` to whole-clip background identity: architecture,
  geography, palette, and lighting sources.

## Choose the angle that matches the camera

- Pick the scene angle whose viewpoint matches the shot's camera position and screen
  direction. A reverse shot uses the reverse angle, not the establishing front.
- If no existing angle matches the planned camera, generate that angle from the
  canonical plate. Do not fake the view with an unrelated angle.

## Keep fixed landmarks consistent

- A door, window, or staircase stays on the same side of frame for a given camera
  axis. When the camera reverses, the landmark flips predictably, not randomly.
- Light direction and time of day stay constant unless the story changes them.
- Fixed furniture does not move between shots; only props a character handles move.

## Reuse the anchored scene asset

- The project continuity anchor pins one scene asset per `scene_id`. Reuse it for
  every shot in that location; vary only the angle `file_key`.
- Do not swap in a different room asset for the same `scene_id` mid-project.
- Actor, costume, and prop turnaround backgrounds never replace the room. The scene
  reference owns the complete background.

## When the room genuinely changes

- A real story change (damage, time jump, redecorate) is a new scene asset or a new
  approved Layout state, not a silent edit. Record it so later shots stay coherent.

## Ground structure in the Picture, not the prose

- The Scene Picture owns the real structure: walls, openings, and especially any
  vehicle or large object. A ref's `visual_lock` records what is visibly there.
- Never describe a feature the Picture does not show. Do not add a cabin, cab, roof,
  ceiling or roof lining, windshield, window glass, or doors to a vehicle that is
  visibly an open frame or flatbed; do not add a steering wheel to a handlebar
  vehicle. If the reference is open, write it as open and say what is absent.
- Authored shot text (`camera_angle`, `composition`, `shot_type`, `script_beat`) is
  not evidence. It can be stale after a scene asset is replaced, so when it names a
  structure the Picture does not show, follow the Picture and omit the structure.
