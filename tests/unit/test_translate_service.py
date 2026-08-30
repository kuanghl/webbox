"""Unit tests for the translate service with a mocked babeldoc pipeline.

The real babeldoc import is heavy and side-effectful, so a minimal fake
package tree is injected into ``sys.modules``; the service imports babeldoc
lazily inside :meth:`TranslateService.run`, which makes this reliable.
"""

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from src.core.store import UserSettings
from src.modules.translate.interfaces import (
    ProgressEvent,
    TranslateJob,
    TranslateOutcome,
    TranslateStage,
)
from src.modules.translate.service import TranslateService


class _FakePipeline:
    """Holds per-test events/behavior for the fake babeldoc pipeline."""

    def __init__(self) -> None:
        """Start with an empty event list and no exception."""
        self.events: list[dict] = []
        self.exception: BaseException | None = None
        self.translator: SimpleNamespace | None = None
        self.config: SimpleNamespace | None = None

    def async_translate(self, config: SimpleNamespace):
        """Fake ``babeldoc.format.pdf.high_level.async_translate``."""
        self.config = config

        async def gen():
            for event in self.events:
                yield event
            if self.exception is not None:
                raise self.exception

        return gen()


@pytest.fixture()
def fake_babeldoc(monkeypatch: pytest.MonkeyPatch) -> _FakePipeline:
    """Install a fake babeldoc package tree into sys.modules."""
    pipeline = _FakePipeline()

    def _module(name: str, **attrs: object) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    class _OpenAITranslator:
        def __init__(self, **kwargs: object) -> None:
            pipeline.translator = SimpleNamespace(**kwargs)

    class _TranslationConfig:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class _DocLayoutModel:
        @staticmethod
        def load_available() -> object:
            return "fake-doclayout"

    _module("babeldoc")
    _module("babeldoc.docvision")
    _module("babeldoc.docvision.base_doclayout", DocLayoutModel=_DocLayoutModel)
    _module("babeldoc.format")
    _module("babeldoc.format.pdf")
    _module("babeldoc.format.pdf.high_level",
            async_translate=pipeline.async_translate)
    _module("babeldoc.format.pdf.translation_config",
            TranslationConfig=_TranslationConfig)
    _module("babeldoc.translator")
    _module("babeldoc.translator.translator", OpenAITranslator=_OpenAITranslator)
    return pipeline


def _job(tmp_path, **overrides) -> TranslateJob:
    """Build a job pointing at an existing file in tmp_path."""
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    base = dict(pdf_path=str(pdf), lang_in="en", lang_out="zh")
    base.update(overrides)
    return TranslateJob(**base)


def _collect(service: TranslateService, job: TranslateJob):
    """Run the service and collect (events, outcome)."""
    async def _run():
        events = []
        outcome = None
        async for item in service.run(job):
            if isinstance(item, TranslateOutcome):
                outcome = item
            else:
                events.append(item)
        return events, outcome

    return asyncio.run(_run())


def test_missing_file_yields_error_outcome(tmp_path) -> None:
    """A nonexistent PDF yields a failed outcome without touching babeldoc."""
    events, outcome = _collect(
        TranslateService(), TranslateJob(pdf_path=str(tmp_path / "nope.pdf"))
    )
    assert events == []
    assert outcome is not None
    assert not outcome.ok
    assert "File not found" in outcome.error


def test_happy_path_maps_stages_and_finish(fake_babeldoc, tmp_path) -> None:
    """Progress events map to coarse stages; finish yields output paths."""
    fake_babeldoc.events = [
        {"type": "progress_start",
         "stage": "Parse PDF and Create Intermediate Representation",
         "stage_current": 0, "stage_total": 10, "overall_progress": 0},
        {"type": "progress_update", "stage": "Translate Paragraphs",
         "stage_current": 5, "stage_total": 10, "overall_progress": 55},
        {"type": "finish",
         "translate_result": SimpleNamespace(
             mono_pdf_path="/out/mono.pdf", dual_pdf_path="/out/dual.pdf")},
    ]
    settings = UserSettings(model="deepseek-chat", api_key="k",
                            base_url="https://api.deepseek.com/v1")
    events, outcome = _collect(TranslateService(settings), _job(tmp_path))

    assert [e.stage for e in events] == [
        TranslateStage.PARSING, TranslateStage.TRANSLATING
    ]
    assert all(isinstance(e, ProgressEvent) for e in events)
    assert events[1].overall_pct == 55
    assert events[1].page == 5 and events[1].total_pages == 10
    assert outcome is not None and outcome.ok
    assert outcome.output_paths == ("/out/mono.pdf", "/out/dual.pdf")
    assert outcome.elapsed_s >= 0

    # translator/config received the settings-backed credentials
    assert fake_babeldoc.translator.model == "deepseek-chat"
    assert fake_babeldoc.translator.api_key == "k"
    assert fake_babeldoc.config.lang_out == "zh"
    assert fake_babeldoc.config.qps == 5


def test_error_event_yields_failed_outcome(fake_babeldoc, tmp_path) -> None:
    """An error event terminates the run with the pipeline's message."""
    fake_babeldoc.events = [{"type": "error", "error": "boom from pipeline"}]
    events, outcome = _collect(TranslateService(), _job(tmp_path))
    assert events == []
    assert outcome is not None
    assert not outcome.ok
    assert outcome.error == "boom from pipeline"


def test_pipeline_exception_yields_failed_outcome(fake_babeldoc, tmp_path) -> None:
    """An exception inside the pipeline becomes a failed outcome."""
    fake_babeldoc.exception = RuntimeError("kaboom")
    events, outcome = _collect(TranslateService(), _job(tmp_path))
    assert outcome is not None
    assert not outcome.ok
    assert "kaboom" in outcome.error


def test_cancellation_propagates(fake_babeldoc, tmp_path) -> None:
    """asyncio.CancelledError must escape the service (not be swallowed)."""
    fake_babeldoc.exception = asyncio.CancelledError()

    async def _run():
        async for _ in TranslateService().run(_job(tmp_path)):
            pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


async def _agen(gen):
    """Consume an async generator into a list (test helper)."""
    return [item async for item in gen]


def test_translate_alias_matches_run(fake_babeldoc, tmp_path) -> None:
    """The TranslateEngine.translate() contract method aliases run()."""
    fake_babeldoc.events = [{"type": "error", "error": "x"}]
    service = TranslateService()
    via_contract = asyncio.run(_agen(service.translate(_job(tmp_path))))
    via_run = asyncio.run(_agen(service.run(_job(tmp_path))))
    assert via_contract == via_run
    assert isinstance(via_contract[0], TranslateOutcome)