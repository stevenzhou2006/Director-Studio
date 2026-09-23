# Poem subtitle overlay (vertical calligraphy)

Use `overlay_poem_subtitles` to burn a Tang-poem title card and traditional
vertical calligraphy columns onto an existing clip. It is CPU only (ffmpeg +
Pillow), so it never waits for the GPU.

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

Get every `start_s` from ASR word timestamps on the padded recitation audio
(for example faster-whisper `word_timestamps=True`), picking the first word of
each line as the start. **Never guess or evenly distribute the starts.** ASR
garbles dialect characters differently per render, so locate each line as the
first word after a long pause instead of matching a guessed character.

## QC before delivery

- Vision-check the actual characters and confirm the columns do not cover a
  face or the main facial expression.
- A passing encode does not mean the text rendered; verify the title and column
  pixels against the un-overlaid clip.
- Single-frame PNG overlays must be looped (`-framerate 24 -loop 1 -i`) or the
  alpha fade at `st>0` never fires and the overlay is invisible. The renderer
  already does this and always encodes `yuv420p` + `+faststart`.
