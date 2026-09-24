# Poem subtitle overlay (vertical calligraphy)

## Step 1 — record the poem on the Shot (`set_poem`)

For any poem-recitation shot, call `set_poem` with the verified `title`, `author`,
`dynasty`, and the ordered `lines` BEFORE you generate the Layout. This is what
makes the text appear without asking the image model to draw it: the Layout gets a
font-composited titled preview (《title》 + `dynasty · author` + seal, plus the
opening line as a vertical column) while the H3-fed frame stays text-free. Line
`start_s` is optional — it is auto-derived later from the bound recitation audio.
Verify author/dynasty against a reliable source; never guess them.

## Step 2 — burn synced subtitles onto the clip (`overlay_poem_subtitles`)

Use `overlay_poem_subtitles` to burn the title card and traditional vertical
calligraphy columns onto an existing clip. It reads the poem you recorded with
`set_poem` (title/author/dynasty/seal/lines all fall back to the Shot), so you can
call it with just the source. It is CPU only (ffmpeg + Pillow), so it never waits
for the GPU.

## What it renders

- Title card at t≈2s: 《title》 in Ma Shan Zheng calligraphy, `dynasty · author`
  in Noto Serif, a thin rule, and a small red seal — fade in 0.8s, hold, fade
  out.
- Poem lines as vertical columns on the right, read top-down, columns
  right-to-left. Each column fades in **exactly when its line starts** being
  spoken and stays until the end; a red seal follows the last column.
- The geometry is a 576×1024 reference design scaled to the source height.
  Override `width`/`height` only when the clip is not the expected portrait
  frame.

## Source selection

- `source_shot_id` resolves the newest succeeded H3 clip for that shot; add
  `source_version="vN"` or `source_job_id` to choose a specific generation, and
  `output_kind="raw"` for the unenhanced video.
- `source_job_id` accepts any succeeded project job that has a `video` or
  `video_raw` output (for example a `concatenate_shots` result).

## Timing (critical)

Omit `start_s` and the tool auto-derives every line start from ASR word
timestamps on the shot's bound recitation audio (faster-whisper, segment/pause
aligned — never character-matched, since the accent garbles glyphs). You only need
to supply the ordered line texts. **Never guess or evenly distribute the starts by
hand.** If you do pass explicit `start_s`, those win.

The resolved poem (title/author/dynasty/seal/lines) is saved back to
`shot.meta.poem`, so a later `queue_ref_frame` for the same shot reuses it and
produces the font-composited `layout_titled` preview automatically.

## QC before delivery

- Vision-check the actual characters and confirm the columns do not cover a
  face or the main facial expression.
- A passing encode does not mean the text rendered; verify the title and column
  pixels against the un-overlaid clip.
- Single-frame PNG overlays must be looped (`-framerate 24 -loop 1 -i`) or the
  alpha fade at `st>0` never fires and the overlay is invisible. The renderer
  already does this and always encodes `yuv420p` + `+faststart`.
