"""Abstract interfaces for the translate module (dependency inversion)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum


class TranslateStage(StrEnum):
    """Coarse progress stages surfaced to the UI."""

    PARSING = "parsing"
    TRANSLATING = "translating"
    LAYOUT = "layout"
    GENERATING = "generating"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProgressEvent:
    """One progress update consumed by UI pollers.

    Attributes:
        stage: Current coarse stage.
        page: Page/item being processed (0 when unknown).
        total_pages: Total pages/items (0 when unknown).
        message: Short human-readable detail (babeldoc stage name).
        overall_pct: Overall progress 0-100 (0 when unknown).
    """

    stage: TranslateStage
    page: int = 0
    total_pages: int = 0
    message: str = ""
    overall_pct: int = 0


@dataclass(frozen=True)
class TranslateJob:
    """Inputs for one translation run.

    Attributes:
        pdf_path: Path of the input PDF.
        lang_in: Source language code (babeldoc, e.g. ``en``).
        lang_out: Target language code (babeldoc, e.g. ``zh``).
        provider: Provider display name (see store.PROVIDER_DEFAULTS).
        model: Model name for the OpenAI-compatible endpoint.
        api_key: API key (may be empty for local providers).
        base_url: Provider base URL.
        pages: Optional page range string, e.g. ``1-5`` (empty = all).
        dual: Produce bilingual (dual) output.
        mono: Produce monolingual output.
        qps: Queries-per-second limit for the LLM API.
        output_dir: Output directory (empty = babeldoc default).
    """

    pdf_path: str
    lang_in: str = "en"
    lang_out: str = "zh"
    provider: str = "DeepSeek"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    pages: str = ""
    dual: bool = True
    mono: bool = False
    qps: float = 5.0
    output_dir: str = ""


@dataclass(frozen=True)
class TranslateOutcome:
    """Final result of a translation run.

    Attributes:
        ok: Whether the run finished successfully.
        output_paths: Generated PDF paths (mono/dual as available).
        error: Error message when ``ok`` is False.
        elapsed_s: Wall-clock seconds of the run.
    """

    ok: bool
    output_paths: tuple[str, ...] = ()
    error: str = ""
    elapsed_s: float = 0.0


class TranslateEngine(ABC):
    """Contract for PDF translation engines."""

    @abstractmethod
    def translate(
        self, job: TranslateJob
    ) -> AsyncIterator[ProgressEvent | TranslateOutcome]:
        """Run a translation, yielding progress then a final outcome.

        Args:
            job: Translation inputs.

        Yields:
            :class:`ProgressEvent` updates followed by one
            :class:`TranslateOutcome`.
        """
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator
