from ..registry import register_pipeline
from .pipeline import PoemOverlayPipeline

POEM_OVERLAY_PIPELINE = register_pipeline(PoemOverlayPipeline())

__all__ = ["POEM_OVERLAY_PIPELINE", "PoemOverlayPipeline"]
