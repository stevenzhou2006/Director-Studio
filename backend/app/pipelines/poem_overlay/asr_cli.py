#!/usr/bin/env python3
"""Standalone faster-whisper word-timestamp CLI.

Run by an external Python that already has ``faster-whisper`` installed (NOT the
Director Studio backend venv). Emits a single JSON object on stdout:

    {"words": [{"word": str, "start": float, "end": float}, ...]}

Used by ``poem_overlay.timing`` to derive per-line recitation start times without
pulling ctranslate2 into the service venv. Kept import-isolated so the system
interpreter needs only ``faster-whisper``.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="faster-whisper word timestamps")
    parser.add_argument("--in", dest="inp", required=True, help="audio file path")
    parser.add_argument("--model", default="medium", help="faster-whisper model size")
    parser.add_argument("--language", default="zh", help="ISO language code")
    parser.add_argument(
        "--cache",
        default=None,
        help="faster-whisper download_root / cache dir",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="beam size for transcription",
    )
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - environment dependent
        sys.stderr.write(f"faster-whisper not importable: {exc}\n")
        return 3

    kwargs: dict[str, object] = {"device": "cpu", "compute_type": "int8"}
    if args.cache:
        kwargs["download_root"] = args.cache

    try:
        model = WhisperModel(args.model, **kwargs)
        segments, _info = model.transcribe(
            args.inp,
            language=args.language or None,
            word_timestamps=True,
            beam_size=max(1, args.beam_size),
        )
        words: list[dict[str, object]] = []
        seg_out: list[dict[str, object]] = []
        for segment in segments:
            seg_out.append(
                {
                    "text": segment.text,
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                }
            )
            for word in segment.words or []:
                words.append(
                    {
                        "word": word.word,
                        "start": round(float(word.start), 3),
                        "end": round(float(word.end), 3),
                    }
                )
    except Exception as exc:  # noqa: BLE001 - surface any ASR failure to caller
        sys.stderr.write(f"asr_cli failed: {exc}\n")
        return 1

    json.dump(
        {"words": words, "segments": seg_out}, sys.stdout, ensure_ascii=False
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
