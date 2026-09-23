"""Qwen3-TTS ComfyUI workflow builder and the 隆昌腔 dialect recipe.

Ported from the Hermes ``comfyui-tts`` skill (verified respelling recipe). The
real node names on the ComfyUI host are ``FB_Qwen3TTSVoiceDesign`` (free-form
natural-language voice design), ``FB_Qwen3TTSCustomVoice`` (preset speaker, e.g.
``Eric`` = native Sichuan dialect), and ``FB_Qwen3TTSVoiceClone``.
"""

from __future__ import annotations

import random
from typing import Any

from ...core.schemas import ComfyImageRef

NODE_TTS = "15"
NODE_SAVE = "11"

STYLES = ("longchang-girl", "eric", "custom")

DEFAULT_AGE = "六七岁"
DEFAULT_RHYME = "韵脚字拖长音，"
DEFAULT_EMOTION = "带着淡淡的忧伤和思念，"
DEFAULT_ERIC_INSTRUCT = "深情、缓慢地吟诵，句间停顿长一些。"
DEFAULT_ERIC_SPEAKER = "Eric"

# The proven 隆昌腔 recipe. The character-level respelling clause is what makes
# the accent land; dropping it silently produces 普通话 however strong the
# timbre description is.
RECIPE = (
    "用四川隆昌口音（内江片的四川话）吟诵古诗，不是成都腔。说话人是一个四川隆昌的小女孩，{age}，"
    "奶声奶气的童声，隆昌腔很重：翘舌音全读成平舌音，{respell}"
    "整首读得非常慢、一字一顿、像老诗人吟诗一样深沉有感情，{rhyme}"
    "句与句之间留很长的停顿，{emotion}"
    "注意：只读文字内容，所有标点符号都不要读出来。"
)

# Curated 翘舌→平舌 respellings verified on this pipeline plus unambiguous
# additions. Only pairs whose characters appear in the poem are used.
RESPELL_PAIRS: tuple[tuple[str, str], ...] = (
    ("长", "藏"),
    ("深", "森"),
    ("知", "资"),
    ("照", "早"),
    ("识", "思"),
    ("处", "粗"),
    ("春", "村"),
    ("出", "粗"),
    ("时", "思"),
    ("是", "四"),
    ("诗", "思"),
    ("山", "三"),
    ("生", "森"),
    ("城", "层"),
    ("树", "素"),
    ("声", "森"),
)


def parse_respell(raw: str | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in (raw or "").split(","):
        token = chunk.strip()
        if not token or "=" not in token:
            continue
        left, right = token.split("=", 1)
        left = left.strip()
        right = right.strip()
        if left and right:
            pairs.append((left, right))
    return pairs


def auto_respell(text: str) -> list[tuple[str, str]]:
    """Pick known respellings for characters that actually occur in the text."""
    present = set(text or "")
    return [(a, b) for a, b in RESPELL_PAIRS if a in present]


def _respell_clause(pairs: list[tuple[str, str]]) -> str:
    return "".join(f"'{a}'读成接近'{b}'、" for a, b in pairs)


def build_instruct(
    *,
    style: str,
    text: str,
    respell: str | None = None,
    age: str = DEFAULT_AGE,
    rhyme: str = DEFAULT_RHYME,
    emotion: str = DEFAULT_EMOTION,
    instruct: str | None = None,
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Return (instruct, respell_pairs_used, warnings)."""
    warnings: list[str] = []
    if style == "eric":
        return (instruct or DEFAULT_ERIC_INSTRUCT), [], warnings
    if style == "custom":
        if not instruct or not instruct.strip():
            raise ValueError("custom style requires an instruct")
        return instruct.strip(), [], warnings

    pairs = parse_respell(respell)
    if not pairs:
        pairs = auto_respell(text)
    if not pairs:
        warnings.append(
            "no known 隆昌 respelling pairs were found in the text; the accent "
            "may drift toward 普通话 — supply explicit respell pairs"
        )
    body = RECIPE.format(
        age=age or DEFAULT_AGE,
        respell=_respell_clause(pairs),
        rhyme=rhyme or "",
        emotion=emotion or "",
    )
    return body, pairs, warnings


def build_tts_prompt(
    *,
    text: str,
    instruct: str,
    style: str,
    seed: int | None,
    job_id: str,
    speaker: str = DEFAULT_ERIC_SPEAKER,
    model_choice: str = "1.7B",
    language: str = "Chinese",
    device: str = "cuda",
    precision: str = "bf16",
    top_p: float = 0.8,
    top_k: int = 20,
    temperature: float = 1.0,
    repetition_penalty: float = 1.05,
    max_new_tokens: int = 2048,
) -> tuple[dict[str, Any], int]:
    resolved_seed = seed if seed is not None else random.randint(0, 2**32 - 1)
    common = {
        "text": text,
        "model_choice": model_choice,
        "device": device,
        "precision": precision,
        "language": language,
        "seed": resolved_seed,
        "max_new_tokens": max_new_tokens,
        "top_p": top_p,
        "top_k": top_k,
        "temperature": temperature,
        "repetition_penalty": repetition_penalty,
        "unload_model_after_generate": True,
    }
    if style == "eric":
        node: dict[str, Any] = {
            "class_type": "FB_Qwen3TTSCustomVoice",
            "inputs": {
                **common,
                "speaker": speaker or DEFAULT_ERIC_SPEAKER,
                "instruct": instruct,
            },
        }
    else:
        node = {
            "class_type": "FB_Qwen3TTSVoiceDesign",
            "inputs": {
                **common,
                "instruct": instruct,
                "attention": "sdpa",
            },
        }
    safe_job = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)[:48]
    prompt = {
        NODE_TTS: node,
        NODE_SAVE: {
            "class_type": "SaveAudio",
            "inputs": {
                "filename_prefix": f"director-studio/{safe_job}/tts",
                "audio": [NODE_TTS, 0],
            },
        },
    }
    return prompt, resolved_seed


def map_history_outputs(
    history: dict[str, Any],
    *,
    job: Any | None = None,
) -> dict[str, ComfyImageRef]:
    del job
    outputs = history.get("outputs") or {}
    node_out = outputs.get(NODE_SAVE) or outputs.get(str(NODE_SAVE)) or {}
    audio = node_out.get("audio") or node_out.get("files") or []
    mapped: dict[str, ComfyImageRef] = {}
    for index, item in enumerate(audio):
        if not isinstance(item, dict):
            continue
        key = "audio" if index == 0 else f"audio_{index + 1}"
        mapped[key] = ComfyImageRef(
            filename=str(item.get("filename") or ""),
            subfolder=str(item.get("subfolder") or ""),
            type=str(item.get("type") or "output"),
        )
    return mapped
