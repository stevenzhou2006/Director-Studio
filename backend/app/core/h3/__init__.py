"""H3 Ref2VA prompt composition/validation and frame grid."""

from .frames import frames_for_audio_seconds, frames_for_seconds
from .prompt import (
    SECTION_KEYS,
    compose_h3_prompt,
    ensure_audio_bindings_in_sections,
    validate_h3_prompt,
    validate_required_picture_bindings,
)

__all__ = [
    "SECTION_KEYS",
    "compose_h3_prompt",
    "ensure_audio_bindings_in_sections",
    "frames_for_seconds",
    "frames_for_audio_seconds",
    "validate_h3_prompt",
    "validate_required_picture_bindings",
]
