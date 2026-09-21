# H3 prompt writing

## Bind real conditioning

Bind every active Layout to its real `<Picture N>` and name the geography, blocking, or object state it adds. Treat all Pictures as whole-clip conditioning; timing belongs only in `detailed_description`. Multiple Layouts may describe compatible states within one continuous beat, but never claim that one activates at a timestamp. A continuity / tail-frame Layout is an ordinary Picture: never call it a first frame, last-frame socket, or an image that activates only at the beginning. It may preserve blocking, wardrobe, and geography carried from a prior shot.

## Lock actor identity and wardrobe

Each actor reference carries an `asset_name` and a `picture_index`. Bind every named actor to that actor's own `<Picture N>` exactly, and never swap, merge, or reassign actor Pictures, even when a shot holds two or more actors. Species, face, hair, fur, wardrobe, and accessories come only from the actor Picture and its approved metadata. Never invent, recolor, or add garments, hairstyles, colors, or accessories, and never carry wardrobe, hair, or color claims out of a Layout's `visual_analysis` — that analysis covers composition, blocking, and lighting only. If no approved appearance description exists, defer to the Picture instead of describing it, for example "LILY, exactly as shown in `<Picture 2>`".

## Write one feasible clip

Preserve exact dialogue once, keep every timing interval within `duration_s`, and state required non-appearance positively. Use approved metadata and describe motion directly without assigning Pictures to time windows.

## Escalate incompatible reveals

Recommend splitting when early leakage of a subject or object would invalidate the shot. Do not pretend that Picture ordering can conceal a state from the rest of the clip.
