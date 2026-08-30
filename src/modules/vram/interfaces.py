"""Abstract interfaces for the VRAM module (dependency inversion).

Frontends depend on :class:`VramCalculator`, not on the concrete service,
mirroring the adapter-contract idea from ``docs/refer-llm-gpu-vram-calculator.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import VramEstimate, VramRequest


class VramCalculator(ABC):
    """Contract for VRAM estimation engines."""

    @abstractmethod
    def estimate(self, request: VramRequest) -> VramEstimate:
        """Estimate VRAM for a request.

        Args:
            request: Model, GPU and workload parameters.

        Returns:
            The estimate with per-item breakdown.

        Raises:
            ValueError: When required parameters are missing or invalid.
        """

    @abstractmethod
    async def fetch_model_config(self, model_id: str) -> dict | None:
        """Fetch a model config (HuggingFace) for preset-less models.

        Args:
            model_id: HuggingFace repo id, e.g. ``Qwen/Qwen2.5-7B-Instruct``.

        Returns:
            Parsed config dict, or ``None`` when unavailable.
        """
