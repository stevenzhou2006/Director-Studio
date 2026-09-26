# Reference-frame generation

## Follow the imported scene assets' style

The imported scene assets are the style authority. Every Layout must match the
medium, palette, lighting, and rendering style of the scene image attached to it;
the pipeline adds this guard automatically whenever a scene asset is in the
reference pack. Never invent an art style and never derive one from the script's
production brief — a style that is not present in the scene assets must not appear
in the Layout. Describe the scene image in the prompt as controlling the style as
well as the geography, so the frame inherits how the scene is rendered, not just
what it contains.

Only call `set_style_lock` when the user explicitly asks for a specific art
style, or asks to keep/preserve the scene's style (保留原风格 / 画风要一致). The
lock is then injected into every reference-frame generation and overrides the
scene assets. Do not set it on your own initiative: a lock that differs from the
scene assets forces every frame away from them. Pass an empty style to clear a
lock and return to following the scene assets.

When the user wants the project to keep the scene's own style, prefer
`set_style_lock` with `from_scene` (or `from_scene:<scene_asset_id>`): the style
sentence is derived once from the scene image and every shot then carries the
identical wording, instead of each shot's visual director re-describing the
style and drifting. Never derive the lock from the script's production-brief
prose — if the brief names a style that is not visible in the scene image, the
brief is wrong for generation purposes.

The pipeline also enforces the lock deterministically: if a prompt names an art
medium (ink-wash/水墨/青绿/watercolor/gongbi/油画 etc.) that the lock does not
contain, a STYLE CONTRADICTION GUARD is appended telling the model to ignore
those words. When repairing a rejected Layout, the rejected frame's rendering
medium is never "what already works" unless it matches the lock or the scene
image — re-assert the correct medium explicitly.

For Layouts whose camera angle differs from the scene master's viewpoint, the
pack builder automatically selects the scene asset's angle plate that matches
the shot's camera direction (back/reverse, left/right side, front-left/right,
bird's-eye, low angle) so the background geography stays grounded. `qc_layout`
checks both cast count and style/scene match (medium + background geography)
before a Layout should be accepted.

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
