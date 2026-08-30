"""Translate tab: PDF path/provider form, live progress, cancellation.

Mirrors ``nicegui/pages/translate_page.py``: form validation, provider
default fill-in, progress display and outcome rendering. The babeldoc
pipeline runs in an app worker so the UI stays responsive; cancel
aborts the worker (see docs/refer-textual.md).
"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Input, ProgressBar, Select, Static

from ....core import i18n
from ....core.constants import DEFAULT_LANG_IN, DEFAULT_LANG_OUT, TRANSLATE_LANGUAGES
from ....core.context import AppContext
from ....core.store import PROVIDER_DEFAULTS, SettingsStore
from ....modules.translate.interfaces import (
    ProgressEvent,
    TranslateJob,
    TranslateOutcome,
)

_WORKER_GROUP = "translate"


class TranslatePage(VerticalScroll):
    """PDF translation form with live progress and worker cancellation."""

    DEFAULT_CSS = """
    TranslatePage {
        height: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, ctx: AppContext) -> None:
        """Initialize with the shared application context.

        Args:
            ctx: Application context (settings + translate service).
        """
        super().__init__()
        self.ctx = ctx
        # NB: not named `_running` — that attribute belongs to Textual's
        # MessagePump (set True on mount) and would break the guard below.
        self._translate_running = False

    def compose(self) -> ComposeResult:
        """Build the form, progress bar and result area."""
        s = self.ctx.settings.load()
        yield Static(i18n.tr("tr.title"))
        yield Static(i18n.tr("tr.file_path"))
        yield Input(id="pdf_path", placeholder="/path/to/document.pdf")
        yield Static(i18n.tr("tr.source_lang"))
        yield Select(_lang_options(), id="lang_in", value=DEFAULT_LANG_IN)
        yield Static(i18n.tr("tr.target_lang"))
        yield Select(_lang_options(), id="lang_out", value=DEFAULT_LANG_OUT)
        yield Static(i18n.tr("tr.provider"))
        yield Select(_provider_options(), id="provider", value=s.provider)
        yield Static(i18n.tr("tr.model"))
        yield Input(id="model", value=s.model)
        yield Static(i18n.tr("tr.base_url"))
        yield Input(id="base_url", value=s.base_url)
        yield Static(i18n.tr("tr.api_key"))
        yield Input(id="api_key", value=s.api_key, password=True)
        yield Static(i18n.tr("tr.pages"))
        yield Input(id="pages")
        yield Static(i18n.tr("tr.qps"))
        yield Input(id="qps", value="5")
        yield Static(i18n.tr("tr.output_dir"))
        yield Input(id="output_dir")
        yield Checkbox(i18n.tr("tr.dual"), value=True, id="dual")
        yield Checkbox(i18n.tr("tr.mono"), value=False, id="mono")
        with Horizontal():
            yield Button(i18n.tr("common.start"), id="btn_start", variant="success")
            cancel = Button(i18n.tr("common.cancel"), id="btn_cancel", variant="error")
            cancel.styles.display = "none"
            yield cancel
        yield Static(i18n.tr("status.idle"), id="status")
        yield Static("", id="stage")
        yield ProgressBar(total=100, show_percentage=False, show_eta=False, id="bar")
        yield Static("", id="result")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route start/cancel clicks."""
        if event.button.id == "btn_start":
            self._start()
        elif event.button.id == "btn_cancel":
            self.workers.cancel_group(self, _WORKER_GROUP)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Fill model/URL defaults when the provider changes."""
        if event.select.id != "provider":
            return
        model, url = SettingsStore.provider_defaults(event.value)
        if model:
            self.query_one("#model", Input).value = model
        if url:
            self.query_one("#base_url", Input).value = url

    def _start(self) -> None:
        """Validate the form and launch the translation worker."""
        if self._translate_running:
            return
        job = self._collect_job()
        if job is None:
            return
        self._translate_running = True
        self._set_running_ui(True)
        self.run_worker(
            self._run(job), name="translate", group=_WORKER_GROUP, exclusive=True
        )

    async def _run(self, job: TranslateJob) -> None:
        """Consume the translation generator, updating progress widgets.

        Args:
            job: Translation inputs.
        """
        try:
            async for event in self.ctx.translate.run(job):
                if isinstance(event, TranslateOutcome):
                    self._render_outcome(event)
                else:
                    self._render_progress(event)
        except asyncio.CancelledError:
            self._set_status(i18n.tr("status.cancelled"))
            raise
        finally:
            self._translate_running = False
            self._set_running_ui(False)

    def _collect_job(self) -> TranslateJob | None:
        """Build a job from the form, or notify and return None if invalid."""
        pdf = self.query_one("#pdf_path", Input).value.strip()
        if not pdf:
            self.app.notify(i18n.tr("tr.no_file"), severity="warning")
            return None
        provider = self.query_one("#provider", Select).value
        api_key = self.query_one("#api_key", Input).value
        if not api_key and provider != "Ollama":
            self.app.notify(i18n.tr("tr.no_api_key"), severity="warning")
            return None
        return TranslateJob(
            pdf_path=pdf,
            lang_in=self.query_one("#lang_in", Select).value,
            lang_out=self.query_one("#lang_out", Select).value,
            provider=provider,
            model=self.query_one("#model", Input).value,
            api_key=api_key,
            base_url=self.query_one("#base_url", Input).value,
            pages=self.query_one("#pages", Input).value,
            dual=self.query_one("#dual", Checkbox).value,
            mono=self.query_one("#mono", Checkbox).value,
            qps=self._qps(),
            output_dir=self.query_one("#output_dir", Input).value,
        )

    def _qps(self) -> float:
        """Parse the QPS input (falls back to 1.0 when empty/invalid)."""
        raw = self.query_one("#qps", Input).value.strip()
        try:
            return float(raw) if raw else 1.0
        except ValueError:
            return 1.0

    def _set_status(self, text: str) -> None:
        """Update the status line."""
        self.query_one("#status", Static).update(text)

    def _set_running_ui(self, running: bool) -> None:
        """Toggle start/cancel button state for the running flag."""
        self.query_one("#btn_start", Button).disabled = running
        self.query_one("#btn_cancel", Button).styles.display = (
            "block" if running else "none"
        )

    def _render_progress(self, event: ProgressEvent) -> None:
        """Update the status line, stage detail and progress bar."""
        self._set_status(
            f"{i18n.tr('status.running')} — {i18n.tr('tr.stage')}: {event.message}"
        )
        detail = (
            f"{event.page}/{event.total_pages}" if event.total_pages else event.message
        )
        self.query_one("#stage", Static).update(detail)
        self.query_one("#bar", ProgressBar).update(total=100, progress=event.overall_pct)

    def _render_outcome(self, outcome: TranslateOutcome) -> None:
        """Render the final result (success files or error message)."""
        if outcome.ok:
            self._set_status(
                f"{i18n.tr('status.finished')} ({outcome.elapsed_s:.1f}s)"
            )
            self.query_one("#bar", ProgressBar).update(progress=100)
            lines = [
                f"{i18n.tr('tr.result_file')}: {p}" for p in outcome.output_paths
            ]
            self.query_one("#result", Static).update("\n".join(lines))
        else:
            self._set_status(i18n.tr("status.error"))
            self.query_one("#result", Static).update(outcome.error)


def _lang_options() -> list[tuple[str, str]]:
    """(display, code) options for the source/target language selects."""
    return [(name, code) for code, name in TRANSLATE_LANGUAGES.items()]


def _provider_options() -> list[tuple[str, str]]:
    """(name, name) options for the provider select."""
    return [(name, name) for name in PROVIDER_DEFAULTS]
