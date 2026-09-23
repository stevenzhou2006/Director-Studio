from ..registry import register_pipeline
from .pipeline import TtsPipeline

TTS_PIPELINE = register_pipeline(TtsPipeline())

__all__ = ["TTS_PIPELINE", "TtsPipeline"]
