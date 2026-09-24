# Reference-frame generation

## Lock the project style first

Before generating any Layout, make sure the project has one canonical art style.
Call `set_style_lock` with the style from the script's production brief (for
example "Chinese ink-wash blended with blue-green mineral colour wash on rice
paper"). The lock is injected into every reference-frame generation automatically,
so all shots render in the same medium, palette, and background treatment. If the
user says the shots look inconsistent (one ink-wash, one photoreal), the style was
never locked: set it, then regenerate the drifted Layouts with `revise_ref_frame`.
A photographic scene plate controls content and geography only — the style lock
controls the rendering medium, so a photo plate under an ink-wash lock must still
produce an ink-wash frame.

## Normal Qwen request

For each Layout, state its purpose, the state it depicts, an optional time hint, and an ordered pack of one to three real source images. Map that ordered pack only to Qwen's fixed `image1`, `image2`, and `image3` inputs; there is no fourth source slot.

## Explicit GPT request

When the user explicitly chooses GPT or ChatGPT image generation, use `queue_gpt_ref_frame` and choose an ordered source pack from real inventory. If no provider is specified, use the local `queue_ref_frame` tool. A capability question is not a request to generate, and a provider failure must not trigger fallback to the other provider. Use as many references as have distinct production jobs; do not add images merely to fill slots. The first attached source is `Image1`, the second is `Image2`, and so on.

Author the final `generation_prompt`. Name every attached image and state what it controls: identity, wardrobe, set geometry, prop design, blocking, or continuity. Request one final cinematic frame rather than a collage, split screen, contact sheet, or turnaround. `ImageN` order is generation evidence only and does not imply H3 timing.

Treat every Actor image as an authoritative character anchor, not a loose style reference. Preserve the same exact face, hair, body proportions, and approved wardrobe; never summarize its job as “identity only.” Clothing may change only when the user explicitly requests it or an attached Costume image controls it. Choose exact file keys: `bust_threeview` is strongest for facial fidelity, while `master` or `fullbody_threeview` carries full-body wardrobe evidence. When both face and wardrobe matter and the reference budget allows, attach both with separate jobs.

Example with four sources:

```text
Create one final cinematic frame in 16:9. Image1 controls the archive corridor geometry and camera axis. Image2 controls Lu's identity and navy uniform. Image3 controls the newcomer's identity and dark coat. Image4 controls the recorder's exact design. Show Lu foreground-left at the desk, the newcomer entering through the marked rear door, and the recorder newly visible between Lu's hands. Preserve identities, wardrobe, set proportions, eyelines, and prop shape. Return one image only; no collage, split screen, labels, borders, or contact sheet.
```

## Prompt construction

Explain each source's identity, design, and spatial contribution in the Qwen prompt. Preserve source order, use exact inventory and file keys, and describe the desired composition as a visual target rather than a guaranteed video endpoint.

## Poem title / attribution frames

Never ask the image model to render Chinese characters, a poem title, an
author/dynasty line, or a seal — Qwen and H3 garble small CJK glyphs and hallucinate
extra characters. When a shot carries a poem, the title card (`《title》` in Ma Shan
Zheng + `dynasty · author` in Noto Serif + rule + red seal) is composited in post
with real fonts. In the Layout prompt, leave the right vertical margin as clean,
empty rice-paper negative space and request no on-screen text. The pipeline adds
this guard automatically when `shot.meta.poem` is set, and emits a separate
`layout_titled` preview; the text-free `layout` stays the H3 reference so H3 never
morphs the attribution.

## Repair discipline

Rejected Layouts are diagnostic-only: never reuse one as a Qwen or GPT input or an H3 `<Picture N>` reference. Use it only to diagnose the failure, then generate from approved sources and the concrete repair goal.
