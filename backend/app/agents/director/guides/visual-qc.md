# Visual QC

## Run the cast-count check first

Before judging anything else, call `qc_layout` on the generated Layout. It counts
the distinct animals/characters in the frame and compares them to the shot's bound
actor references. A positive prompt cannot stop the image model from cloning a
character (one cat rendered twice) or inventing an extra animal, so this check is
what catches it. A failed cast QC means the Layout must be revised with
`revise_ref_frame` — never accept a frame with a duplicated or extra character,
and never accept one that is missing a bound cast member.

## Review the actual Layout

Judge the actual Layout against its purpose: identity, wardrobe, geometry, blocking, eyelines, prop count and design, requested action, and unrelated objects. A completed generation is pending review, not usable by default.

## Compare candidates

Compare sibling candidates for compatible geometry, screen direction, identity, wardrobe, and object state. Select only a candidate that supports the intended shot and its continuity dependencies.

## Record the decision

Classify the Layout as usable, usable with repair, or rejected, and record observed evidence rather than assuming success from a completed job.
