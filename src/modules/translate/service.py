"""Babeldoc-backed PDF translation service.

Wraps ``babeldoc.format.pdf.high_level.async_translate`` (an async
generator of progress-event dicts) into a framework-agnostic async
generator yielding progress tuples and a final
:class:`~src.modules.translate.interfaces.TranslateOutcome`.

Event contract of ``async_translate`` (verified against babeldoc 0.6.4)::

    {"type": "progress_start|progress_update|progress_end",
     "stage": str, "stage_progress": float,
     "stage_current": int, "stage_total": int,
     "overall_progress": float}
    {"type": "finish", "translate_result": TranslateResult}
    {"type": "error", "error": str}
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

from ...core.store import UserSettings
from .interfaces import (
    ProgressEvent,
    TranslateEngine,
    TranslateJob,
    TranslateOutcome,
    TranslateStage,
)

logger = logging.getLogger(__name__)

#: babeldoc stage name → coarse UI stage.
_STAGE_MAP: dict[str, TranslateStage] = {
    "Parse PDF and Create Intermediate Representation": TranslateStage.PARSING,
    "DetectScannedFile": TranslateStage.PARSING,
    "Parse Page Layout": TranslateStage.PARSING,
    "Parse Table": TranslateStage.PARSING,
    "Parse Paragraphs": TranslateStage.PARSING,
    "Parse Formulas and Styles": TranslateStage.PARSING,
    "Automatic Term Extraction": TranslateStage.TRANSLATING,
    "Translate Paragraphs": TranslateStage.TRANSLATING,
    "Typesetting": TranslateStage.LAYOUT,
    "Add Fonts": TranslateStage.GENERATING,
    "Generate drawing instructions": TranslateStage.GENERATING,
    "Subset font": TranslateStage.GENERATING,
    "Save PDF": TranslateStage.GENERATING,
}


class TranslateService(TranslateEngine):
    """PDF translation engine over babeldoc's async pipeline.

    ``run(job)`` is an async generator yielding :class:`ProgressEvent`
    updates followed by one final :class:`TranslateOutcome`.
    """

    def __init__(self, settings: UserSettings | None = None) -> None:
        """Initialize with default provider settings.

        Args:
            settings: User settings supplying default model/key/URL;
                a job's own fields always win.
        """
        self._settings = settings

    def translate(
        self, job: TranslateJob
    ) -> AsyncIterator[ProgressEvent | TranslateOutcome]:
        """Contract method — alias of :meth:`run` (see TranslateEngine).

        Args:
            job: Translation inputs.

        Yields:
            :class:`ProgressEvent` updates and a final
            :class:`TranslateOutcome`.
        """
        return self.run(job)

    async def run(self, job: TranslateJob) -> AsyncIterator[object]:
        """Run a translation as an async generator.

        Args:
            job: Translation inputs.

        Yields:
            :class:`ProgressEvent` updates followed by one final
            :class:`TranslateOutcome`.
        """
        from babeldoc.docvision.base_doclayout import DocLayoutModel
        from babeldoc.format.pdf.high_level import async_translate
        from babeldoc.format.pdf.translation_config import TranslationConfig
        from babeldoc.translator.translator import OpenAITranslator

        start = time.monotonic()
        pdf = Path(job.pdf_path)
        if not pdf.is_file():
            yield TranslateOutcome(ok=False, error=f"File not found: {pdf}")
            return

        settings = self._settings
        api_key = job.api_key or (settings.api_key if settings else "")
        model = job.model or (settings.model if settings else "")
        base_url = job.base_url or (settings.base_url if settings else "")

        translator = OpenAITranslator(
            lang_in=job.lang_in,
            lang_out=job.lang_out,
            model=model,
            base_url=base_url or None,
            api_key=api_key or None,
        )
        config = TranslationConfig(
            translator=translator,
            input_file=str(pdf),
            lang_in=job.lang_in,
            lang_out=job.lang_out,
            doc_layout_model=DocLayoutModel.load_available(),
            pages=job.pages or None,
            output_dir=job.output_dir or None,
            no_dual=not job.dual,
            no_mono=not job.mono,
            qps=max(1, int(job.qps)),
            use_rich_pbar=False,
        )

        logger.info(
            "Translation started: %s %s->%s model=%s qps=%s",
            pdf.name, job.lang_in, job.lang_out, model, job.qps,
        )
        outcome: TranslateOutcome | None = None
        try:
            async for event in async_translate(config):
                etype = event.get("type")
                if etype in ("progress_start", "progress_update", "progress_end"):
                    stage = _STAGE_MAP.get(
                        event.get("stage", ""), TranslateStage.PARSING
                    )
                    yield ProgressEvent(
                        stage=stage,
                        page=int(event.get("stage_current", 0) or 0),
                        total_pages=int(event.get("stage_total", 0) or 0),
                        message=event.get("stage", ""),
                        overall_pct=int(event.get("overall_progress", 0) or 0),
                    )
                elif etype == "finish":
                    result = event.get("translate_result")
                    paths = tuple(
                        str(p)
                        for p in (
                            getattr(result, "mono_pdf_path", None),
                            getattr(result, "dual_pdf_path", None),
                        )
                        if p
                    )
                    outcome = TranslateOutcome(
                        ok=True,
                        output_paths=paths,
                        elapsed_s=round(time.monotonic() - start, 1),
                    )
                    logger.info("Translation finished: %s", paths)
                elif etype == "error":
                    outcome = TranslateOutcome(
                        ok=False,
                        error=str(event.get("error", "unknown error")),
                        elapsed_s=round(time.monotonic() - start, 1),
                    )
                    logger.error("Translation failed: %s", outcome.error)
                    break
        except Exception as exc:  # noqa: BLE001 - surface pipeline errors to UI
            logger.exception("Translation crashed")
            outcome = TranslateOutcome(
                ok=False,
                error=str(exc),
                elapsed_s=round(time.monotonic() - start, 1),
            )
        if outcome is not None:
            yield outcome
