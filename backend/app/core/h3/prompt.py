"""H3 Ref2VA six-section prompt compose and validate."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from app.core.projects.models import PromptSections

SECTION_KEYS: list[str] = [
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]

# UTF-8 replacement character — optional corruption signal
_REPLACEMENT_CHAR = "\ufffd"

_TIMED_ACTION_INTERVAL_PATTERN = re.compile(
    r"(?<![\d.])(?P<start>\d+(?:\.\d+)?)\s*[–—-]\s*"
    r"(?P<end>\d+(?:\.\d+)?)\s*(?:s|seconds?)\b",
    re.IGNORECASE,
)
_TAIL_TRANSITION_VERB_PATTERN = re.compile(
    r"\b(?:continue(?:s|d|ing)?|carry(?:ing|ies|ied)?|unwind(?:s|ing)?|"
    r"dissolv(?:e|es|ed|ing)|transform(?:s|ed|ing)?|morph(?:s|ed|ing)?|"
    r"open(?:s|ed|ing)?|clear(?:s|ed|ing)?|reveal(?:s|ed|ing)?|"
    r"resolv(?:e|es|ed|ing))\b",
    re.IGNORECASE,
)
_TAIL_TRANSITION_NEGATION_PATTERNS = (
    re.compile(r"\bhard[\s-]+cut\b", re.IGNORECASE),
    re.compile(r"\b(?:palette|style)\s+only\b", re.IGNORECASE),
    re.compile(r"\bmust\s+not\s+(?:manifest|be\s+visible)\b", re.IGNORECASE),
    re.compile(r"\b(?:do\s+not|don't|never)\s+(?:show|render|manifest)\b", re.IGNORECASE),
    re.compile(r"\b(?:open|start|begin)(?:s|ing)?\s+(?:directly\s+)?(?:on|with)\b", re.IGNORECASE),
)


def validate_tail_frame_transition_prompt(
    sections: PromptSections,
    selected_layouts: Iterable[dict[str, object]],
) -> None:
    """Require an explicit visible handoff for a selected clip-tail Layout.

    The Picture still conditions the full clip. This validates action prose only;
    it does not claim that the reference is an exact or time-addressable frame.
    """
    if not any(
        bool(layout.get("visible_transition_required"))
        for layout in selected_layouts
    ):
        return

    description = sections.detailed_description
    intervals = list(_TIMED_ACTION_INTERVAL_PATTERN.finditer(description))
    if not intervals or float(intervals[0].group("start")) != 0.0:
        raise ValueError(
            "tail-frame transition must begin in the first action interval at 0 seconds"
        )

    first_start = intervals[0].start()
    first_end = intervals[1].start() if len(intervals) > 1 else len(description)
    first_interval = description[first_start:first_end]
    if any(pattern.search(first_interval) for pattern in _TAIL_TRANSITION_NEGATION_PATTERNS):
        raise ValueError(
            "tail-frame transition cannot be a hard cut, style-only cue, or hidden source state"
        )
    if not _TAIL_TRANSITION_VERB_PATTERN.search(first_interval):
        raise ValueError(
            "tail-frame transition needs a visible carryover and transition action in the first interval"
        )


def validate_required_picture_bindings(
    text: str,
    required_indices: Iterable[int],
    *,
    submitted_picture_indices: Iterable[int] | None = None,
    require_all_submitted: bool = False,
) -> None:
    found_indices = [
        int(value)
        for value in re.findall(r"<Picture\s+(\d+)>", text, re.IGNORECASE)
    ]
    if submitted_picture_indices is not None:
        submitted = {int(index) for index in submitted_picture_indices}
        unexpected = sorted(set(found_indices) - submitted)
        if unexpected:
            tags = ", ".join(f"<Picture {index}>" for index in unexpected)
            raise ValueError(
                f"prompt references unsubmitted Picture tags: {tags}"
            )
    for index in dict.fromkeys(int(value) for value in required_indices):
        tag = f"<Picture {index}>"
        if index not in found_indices:
            raise ValueError(f"missing selected Layout binding: {tag}")
    if require_all_submitted and submitted_picture_indices is not None:
        missing = sorted(submitted - set(found_indices))
        if missing:
            tags = ", ".join(f"<Picture {index}>" for index in missing)
            raise ValueError(
                f"prompt must bind every submitted Picture reference: missing {tags}"
            )


def compose_h3_prompt(sections: PromptSections) -> str:
    """Compose ordered H3 prompt text from PromptSections."""
    parts: list[str] = []
    for key in SECTION_KEYS:
        value = getattr(sections, key)
        parts.append(f"{key}:\n{value}")
    return "\n".join(parts)


def ensure_audio_bindings_in_sections(
    sections: PromptSections,
    audio_bindings: Iterable[tuple[int, str]],
) -> PromptSections:
    """Deterministically bind every submitted voice as ``<Audio N>``.

    The H3 contract requires each submitted audio index to be referenced in the
    prompt (see ``validate_h3_prompt``). The writer LLM sometimes omits the tag,
    which only surfaces as a submit-time rejection. This backstop appends an
    explicit binding clause to ``overall_soundscape`` for any missing index so
    the prompt is always submittable and the audio is bound to the on-screen
    performance. Idempotent: a section that already references the tag is left
    untouched.
    """
    bindings = [
        (int(idx), (label or f"voice {idx}").strip())
        for idx, label in audio_bindings
    ]
    if not bindings:
        return sections
    text = sections.as_ordered_text()
    missing = [(idx, label) for idx, label in bindings if f"<Audio {idx}>" not in text]
    # A diegetic lip-sync directive must be present whenever a voice is bound, even
    # if the writer already referenced <Audio N> as a narrator/voice-over. Without
    # this the model renders a closed, unmoving mouth over the recitation.
    has_lip_sync = "mouth" in text and "sync" in text
    # The mouth cue must also live in detailed_description (the conditioning
    # payload), not only the soundscape: a mouth-hiding composition (top-down into
    # an object, head lowered away from camera) will otherwise defeat lip-sync even
    # when the soundscape says the mouth moves.
    dd_has_mouth = "mouth" in (sections.detailed_description or "").lower()
    if not missing and has_lip_sync and dd_has_mouth:
        return sections
    update: dict[str, str] = {}
    clauses: list[str] = [
        f"The voice/recitation in <Audio {idx}> ({label}) is the authoritative "
        "vocal performance for this shot."
        for idx, label in missing
    ]
    if not has_lip_sync:
        clauses.append(
            "The recitation audio bound to this shot is spoken aloud by the "
            "on-screen character who is reciting — NOT a disembodied narrator "
            "or voice-over. Their mouth, jaw, lips, and breath move visibly in "
            "sync with the words and the delivery timing of the audio; a closed "
            "or unmoving mouth over this recitation is a defect."
        )
    if clauses:
        base = (sections.overall_soundscape or "").strip()
        addition = " ".join(clauses)
        update["overall_soundscape"] = f"{base} {addition}".strip() if base else addition
    if not dd_has_mouth:
        dd = (sections.detailed_description or "").strip()
        cue = (
            "Throughout the recitation the speaking on-screen character's face "
            "and mouth stay visible to camera and their lips, jaw, and mouth move "
            "continuously in sync with the audio; the framing must not hide the "
            "speaker's mouth — do not use a top-down or head-lowered-away "
            "composition while the line is spoken, and keep the mouth region in "
            "clear view."
        )
        update["detailed_description"] = f"{dd} {cue}".strip() if dd else cue
    if not update:
        return sections
    return sections.model_copy(update=update)


# Quote pairs whose contents are treated as a removable spoken/mentioned span.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ("'", "'"),
    ('"', '"'),
    ("\u201c", "\u201d"),
    ("\u300c", "\u300d"),
    ("\u300e", "\u300f"),
)
# Neutral, non-matching stand-ins used when a surplus copy must be removed.
_FALLBACK_REFERENCE = "the recited line"
_BLANK_FILLER = "Ambient sound only."
# Section that carries the authoritative spoken action; kept first.
_SPOKEN_SECTION = "detailed_description"


def _remove_one_surplus(text: str, line: str) -> str:
    """Remove one occurrence of ``line`` from ``text``.

    Prefers deleting a quoted span (quotes included) so the surrounding prose
    stays grammatical; otherwise replaces the bare line with a neutral,
    non-matching reference.
    """
    for open_q, close_q in _QUOTE_PAIRS:
        quoted = f"{open_q}{line}{close_q}"
        if quoted in text:
            stripped = text.replace(quoted, "", 1)
            return re.sub(r"[ \t]{2,}", " ", stripped)
    return text.replace(line, _FALLBACK_REFERENCE, 1)


def enforce_dialogue_occurrences_in_sections(
    sections: PromptSections,
    dialogue: Iterable[str],
    *,
    exempt_text: str = "",
) -> PromptSections:
    """Deterministically make each dialogue line appear exactly the expected times.

    The H3 contract (see ``validate_h3_prompt``) requires each dialogue line to
    appear in the composed prompt exactly once per occurrence in the dialogue
    list. The writer LLM often mentions the same line in several sections, which
    only surfaces as a submit-time rejection (and, when no audio is attached,
    risks the model speaking the line twice). This backstop rewrites the sections
    so the count always matches: surplus copies are removed (keeping the spoken
    occurrence in ``detailed_description`` first), and missing copies are added
    as explicit spoken clauses. Occurrences inside ``exempt_text`` (the GLOBAL
    DIRECTION) are never touched. Idempotent: a section set that already matches
    is returned unchanged.
    """
    lines = [line for line in dialogue if line]
    if not lines:
        return sections

    expected = Counter(lines)
    sentinel = "\u0000DIALOGUE_EXEMPT\u0000"

    # Work on copies with the exempt region masked so it can never be rewritten.
    protected: dict[str, str] = {}
    for field in PromptSections.model_fields:
        original = getattr(sections, field) or ""
        protected[field] = (
            original.replace(exempt_text, sentinel) if exempt_text else original
        )

    keep_order = [_SPOKEN_SECTION] + [
        key for key in SECTION_KEYS if key != _SPOKEN_SECTION
    ]
    remove_order = list(reversed(keep_order))

    for line, total_expected in expected.items():
        # Copies locked inside the GLOBAL DIRECTION can never be removed.
        protected_count = exempt_text.count(line) if exempt_text else 0
        target = total_expected - protected_count
        current = sum(value.count(line) for value in protected.values())

        surplus = current - target
        if surplus > 0:
            for field in remove_order:
                if surplus <= 0:
                    break
                value = protected[field]
                while surplus > 0 and line in value:
                    value = _remove_one_surplus(value, line)
                    surplus -= 1
                protected[field] = value
        elif surplus < 0:
            clauses = [
                f'A speaker delivers the line: "{line}"' for _ in range(-surplus)
            ]
            base = protected[_SPOKEN_SECTION].strip()
            addition = " ".join(clauses)
            protected[_SPOKEN_SECTION] = (
                f"{base} {addition}".strip() if base else addition
            )

    # Restore the exempt region and keep every section body non-empty.
    updates: dict[str, str] = {}
    for field, value in protected.items():
        restored = value.replace(sentinel, exempt_text) if exempt_text else value
        if not restored.strip():
            restored = _BLANK_FILLER
        if restored != (getattr(sections, field) or ""):
            updates[field] = restored
    if not updates:
        return sections
    return sections.model_copy(update=updates)


def validate_h3_prompt(
    prompt: str,
    dialogue: list[str],
    *,
    audio_count: int = 0,
    required_picture_indices: Iterable[int] = (),
    submitted_picture_indices: Iterable[int] | None = None,
    require_all_submitted: bool = False,
) -> None:
    """Validate section order, non-empty bodies, and exact dialogue occurrence.

    Raises ValueError on any contract violation.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")

    if _REPLACEMENT_CHAR in prompt:
        raise ValueError("prompt contains UTF-8 replacement character (corruption)")

    # Positions of each "{key}:" header (first occurrence)
    positions: list[tuple[str, int]] = []
    for key in SECTION_KEYS:
        header = f"{key}:"
        pos = prompt.find(header)
        if pos < 0:
            raise ValueError(f"section order: missing header {header!r}")
        positions.append((key, pos))

    # Strictly increasing positions
    for i in range(1, len(positions)):
        prev_key, prev_pos = positions[i - 1]
        key, pos = positions[i]
        if pos <= prev_pos:
            raise ValueError(
                f"section order: {key!r} at {pos} is not after {prev_key!r} at {prev_pos}"
            )

    # Non-empty section bodies (text between this header and the next, or EOF)
    for i, (key, pos) in enumerate(positions):
        header = f"{key}:"
        start = pos + len(header)
        if i + 1 < len(positions):
            end = positions[i + 1][1]
        else:
            end = len(prompt)
        body = prompt[start:end].strip()
        if not body:
            raise ValueError(f"section {key!r} is empty")

    # Each dialogue line appears once per occurrence in the dialogue list. Two
    # characters can legitimately share the same line (for example a chorus of
    # "hahaha"), so a duplicated line must appear twice in the prompt package.
    dialogue_counts: dict[str, int] = {}
    for line in dialogue:
        if not line:
            raise ValueError("dialogue line is empty")
        dialogue_counts[line] = dialogue_counts.get(line, 0) + 1
    for line, expected in dialogue_counts.items():
        count = prompt.count(line)
        if count != expected:
            expected_text = "exactly once" if expected == 1 else f"exactly {expected} times"
            raise ValueError(
                f"dialogue line must appear {expected_text} (found {count}): {line!r}"
            )

    found_audio_indexes = [int(value) for value in re.findall(r"<Audio\s+(\d+)>", prompt)]
    expected_audio_indexes = list(range(1, audio_count + 1))
    for index in expected_audio_indexes:
        count = found_audio_indexes.count(index)
        if count < 1:
            raise ValueError(f"prompt must reference submitted <Audio {index}>")
    unexpected = sorted(set(found_audio_indexes) - set(expected_audio_indexes))
    if unexpected:
        tags = ", ".join(f"<Audio {index}>" for index in unexpected)
        raise ValueError(f"prompt references unsubmitted Audio tags: {tags}")

    validate_required_picture_bindings(
        prompt,
        required_picture_indices,
        submitted_picture_indices=submitted_picture_indices,
        require_all_submitted=require_all_submitted,
    )
