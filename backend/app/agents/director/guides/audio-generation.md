# Audio generation (ComfyUI Qwen3-TTS)

Use `generate_tts_audio` when the production needs speech audio: a Tang-poem
recitation, narration, off-screen voice-over, an identity-sensitive vocal, or a
reference voice for H3. It calls the local ComfyUI Qwen3-TTS service and saves
the result as a Voice asset in the current project's library.

## Styles

- `longchang-girl` (default) — the verified 四川隆昌小女孩 dialect recitation.
  This style does **not** have a dialect token; the accent comes only from the
  `instruct`, so it REQUIRES a character-level respelling clause. Pass
  `respell` pairs drawn from the poem's own characters, at least three, e.g.
  `"长=藏,深=森,知=资"` (翘舌→平舌: zh/ch/sh → z/c/s). Omitting them silently
  produces clean 普通话 however strongly you describe the timbre. Verify the
  accent from the produced audio, never from the instruct you wrote.
- `eric` — `FB_Qwen3TTSCustomVoice` with `speaker=Eric`, a real
  `sichuan_dialect` Chengdu male voice. Use it when a male Sichuan recitation is
  wanted. This is the user-rejected voice for the 女声 series; do not substitute
  it for `longchang-girl` when the user asked for the little-girl recitation.
- `custom` — supply your own full voice-design `instruct`.
- `saved-speaker` — speak ANY text with a voice the user registered in this
  project's Voice Studio (Voice Cloning). Pass the speaker's id (`spk_...`) or
  exact name in `speaker`. The reference transcript (`ref_text`) and clone
  features are saved with the speaker and load automatically — never pass
  `respell` or `instruct` with this style; the accent rides on the registered
  reference audio. List available speakers with their names before casting.

## Reading discipline

- The model reads everything in `text`, including punctuation and parenthetical
  stage directions. Pass only the words that should be spoken; never embed
  `（停顿）` or comma-heavy text you do not want read.
- It will not produce real non-speech sounds (a written 喵 is pronounced as a
  syllable). Splice a real sample with ffmpeg instead.
- Control duration with the text and the recipe's slow, one-character-at-a-time
  pacing; instruct-based "slow down" is unreliable.

## H3 handoff

- H3 Ref2AV re-synthesises the audio track from its `ref_audio` reference, so
  the reference voice/accent is what the film ships with. Settle the recitation
  **before** any long render; a wrong reference costs a full re-render.
- Pass `lead_silence_s` (for example `1.0`) when the audio will be an H3
  mouth-sync reference so the recitation starts on cue. The padded track is
  returned as `padded_audio_url`.
- H3 voice references are short identity samples. A full recitation is usually
  longer than the 2–15s voice-reference window; when the result reports
  `h3_reference_ready=false`, use it as the production track (or split a short
  phrase) rather than as a casting reference.

## Operating notes

- Real node names on this host are `FB_Qwen3TTSVoiceDesign`,
  `FB_Qwen3TTSCustomVoice`, and `FB_Qwen3TTSVoiceClone`. The `AILab_*` node
  names are not installed and fail with `missing_node_type`.
- If generation fails on import/attribute errors, the ComfyUI TTS environment
  needs its NumPy/transformers pins fixed and the ComfyUI service restarted
  after the change.
