"""Production provider adapters for the Voice Brain Dump workflow.

``OpenAiAccurateStt`` (``adapters.openai_stt``) is deliberately excluded from
this package's exported surface: ADR-0002 authorizes only Deepgram Nova-3 for
production accurate STT, and that adapter exists solely as narrowly-scoped,
explicit test support. Import it directly from its submodule if a test
genuinely needs it.
"""

from .deepgram_stt import DeepgramAccurateStt
from .reconciler import OpenAITextReconciler

__all__ = ["DeepgramAccurateStt", "OpenAITextReconciler"]
