"""Translate page: PDF upload, provider options, live progress, results.

OpenPencil-style layout: top bar, document sidebar, status strip,
SOURCE/TARGET/PROGRESS panels and a bottom action bar. The babeldoc
pipeline runs as an asyncio task inside the page's event loop; a
``ui.timer`` polls the shared :class:`TaskState` so the progress bar
updates without blocking the UI (see docs/refer-nicegui.md §3.3).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from nicegui import ui

from ....core import i18n
from ....core.constants import DEFAULT_LANG_IN, DEFAULT_LANG_OUT, TRANSLATE_LANGUAGES
from ....core.context import AppContext
from ....modules.translate.interfaces import TranslateJob, TranslateOutcome
from ..components import (
    on_provider_change,
    provider_select,
    wb_chip,
    wb_ghost_btn,
    wb_input_bar,
    wb_panel_head,
    wb_primary_btn,
    wb_side_items,
    wb_status_strip,
    wb_top_bar,
)

#: Status dot colors per state.
_DOT_IDLE = "#34d399"
_DOT_RUNNING = "#f0883e"
_DOT_ERROR = "#f87171"


@dataclass
class TaskState:
    """Shared state between the translation task and the UI poller.

    Attributes:
        running: Whether a job is in flight.
        stage: Current stage display name (English, from babeldoc).
        pct: Overall progress 0-100.
        cur: Current item of the stage.
        total: Total items of the stage.
        outcome: Final outcome once finished.
        reported: Whether the final outcome was already rendered once.
    """

    running: bool = False
    stage: str = ""
    pct: int = 0
    cur: int = 0
    total: int = 0
    outcome: TranslateOutcome | None = field(default=None)
    reported: bool = False


def build(ctx: AppContext) -> None:
    """Render the translate page.

    Args:
        ctx: Application context.
    """
    settings = ctx.settings.load()
    state = TaskState()
    pdf_path: dict[str, str] = {}
    task: dict[str, asyncio.Task] = {}
    docs: list[tuple[str, str]] = []

    def _on_upload(e) -> None:
        """Store the uploaded file path (NiceGUI temp file)."""
        pdf_path["path"] = str(e.content.name)
        pdf_path["name"] = e.name
        file_chip.text = e.name
        file_chip.visible = True
        file_hint.text = e.name
        status.text = i18n.tr("tr.status_idle")

    def _doc_items() -> list[tuple[str, str]]:
        """Sidebar entries: translated documents, or an empty hint."""
        return docs or [(i18n.tr("tr.documents_empty"), "")]

    def _render_docs() -> None:
        """Re-render the document sidebar."""
        side.clear()
        wb_side_items(side, i18n.tr("tr.documents").upper(), _doc_items(), -1)

    def reset() -> None:
        """Clear the form for a new translation."""
        pdf_path.clear()
        file_chip.visible = False
        file_hint.text = i18n.tr("tr.drop")
        status.text = i18n.tr("tr.status_idle")
        dot.style(f"background:{_DOT_IDLE}")
        stage_label.text = ""
        bar.value = 0.0
        result_area.clear()

    with ui.column().classes("wb-page w-full"):
        wb_top_bar(i18n.tr("tr.title_bar"), action_label=i18n.tr("tr.new"), on_action=reset)
        with ui.row().classes("wb-body"):
            with ui.column().classes("wb-sidebar gap-2") as side:
                wb_side_items(side, i18n.tr("tr.documents").upper(), _doc_items(), -1)
            with ui.column().classes("wb-main"):
                dot, status, _ = wb_status_strip(
                    _DOT_IDLE, i18n.tr("tr.status_idle"), i18n.tr("tr.meta")
                )
                with ui.column().classes("wb-workspace gap-4"):
                    with ui.column().classes("wb-panel w-full gap-3"):
                        wb_panel_head(i18n.tr("tr.source").upper(), i18n.tr("tr.pdf_only"))
                        file_chip = wb_chip("")
                        file_chip.visible = False
                        ui.upload(
                            auto_upload=True,
                            on_upload=_on_upload,
                        ).props("accept=application/pdf").classes("w-full")
                        ui.label(i18n.tr("tr.upload_hint")).classes("wb-note")

                    with ui.column().classes("wb-panel w-full gap-3"):
                        wb_panel_head(i18n.tr("tr.target").upper())
                        with ui.row().classes("gap-2 w-full"):
                            lang_in = ui.select(
                                options=TRANSLATE_LANGUAGES,
                                value=DEFAULT_LANG_IN,
                                label=i18n.tr("tr.source_lang"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                            lang_out = ui.select(
                                options=TRANSLATE_LANGUAGES,
                                value=DEFAULT_LANG_OUT,
                                label=i18n.tr("tr.target_lang"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                        model_input = ui.input(
                            label=i18n.tr("tr.model"), value=settings.model
                        ).props("dense outlined").classes("w-full")
                        url_input = ui.input(
                            label=i18n.tr("tr.base_url"), value=settings.base_url
                        ).props("dense outlined").classes("w-full")
                        prov = provider_select(
                            settings.provider,
                            on_change=on_provider_change(ctx, model_input, url_input),
                            label=i18n.tr("tr.provider"),
                        ).props("dense outlined")
                        key_input = ui.input(
                            label=i18n.tr("tr.api_key"),
                            value=settings.api_key,
                            password=True,
                            password_toggle_button=True,
                        ).props("dense outlined").classes("w-full")
                        with ui.row().classes("gap-2"):
                            pages_input = ui.input(
                                label=i18n.tr("tr.pages"), value=""
                            ).props("dense outlined").classes("flex-1")
                            qps_input = ui.number(
                                label=i18n.tr("tr.qps"), value=5.0, min=1, step=1
                            ).props("dense outlined").classes("w-24")
                        with ui.row().classes("gap-4"):
                            dual = ui.switch(i18n.tr("tr.dual"), value=True)
                            mono = ui.switch(i18n.tr("tr.mono"), value=False)
                        out_input = ui.input(
                            label=i18n.tr("tr.output_dir"), value=""
                        ).props("dense outlined").classes("w-full")

                    with ui.column().classes("wb-panel w-full gap-3"):
                        wb_panel_head(i18n.tr("common.progress").upper())
                        stage_label = ui.label("").classes("wb-note")
                        bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
                        result_area = ui.column().classes("w-full gap-1")

        with wb_input_bar():
            with ui.row().classes("items-center gap-2.5 w-full no-wrap"):
                with ui.row().classes("wb-inputbox items-center gap-2.5 no-wrap flex-1"):
                    ui.label(i18n.tr("common.file")).classes("wb-inputbox-prefix")
                    file_hint = ui.label(i18n.tr("tr.drop")).classes("wb-inputbox-hint flex-1")
                start_btn = wb_primary_btn(
                    i18n.tr("common.start"), on_click=lambda: start(), icon="play_arrow"
                )
                cancel_btn = wb_ghost_btn(
                    i18n.tr("common.cancel"), on_click=lambda: cancel(), icon="stop"
                )
                cancel_btn.set_visibility(False)

    def _collect_job() -> TranslateJob | None:
        """Build a job from the form, or None when invalid."""
        if "path" not in pdf_path:
            ui.notify(i18n.tr("tr.no_file"), type="warning")
            return None
        if not key_input.value and prov.value != "Ollama":
            ui.notify(i18n.tr("tr.no_api_key"), type="warning")
            return None
        return TranslateJob(
            pdf_path=pdf_path["path"],
            lang_in=lang_in.value,
            lang_out=lang_out.value,
            provider=prov.value,
            model=model_input.value,
            api_key=key_input.value,
            base_url=url_input.value,
            pages=pages_input.value or "",
            dual=dual.value,
            mono=mono.value,
            qps=float(qps_input.value or 1),
            output_dir=out_input.value or "",
        )

    async def _worker(job: TranslateJob) -> None:
        """Consume the translation generator into ``state``."""
        try:
            async for event in ctx.translate.run(job):
                if isinstance(event, TranslateOutcome):
                    state.outcome = event
                else:
                    state.stage = event.message
                    state.pct = event.overall_pct
                    state.cur = event.page
                    state.total = event.total_pages
        finally:
            state.running = False

    def start() -> None:
        """Validate inputs and launch the background translation task."""
        if state.running:
            return
        job = _collect_job()
        if job is None:
            return
        state.running = True
        state.outcome = None
        state.reported = False
        result_area.clear()
        dot.style(f"background:{_DOT_RUNNING}")
        task["t"] = asyncio.create_task(_worker(job))

    def cancel() -> None:
        """Cancel the in-flight translation task."""
        t = task.get("t")
        if t:
            t.cancel()
            state.running = False
            status.text = i18n.tr("status.cancelled")
            dot.style(f"background:{_DOT_IDLE}")

    def _poll() -> None:
        """Refresh progress widgets from the shared state."""
        start_btn.props(f"disable={'true' if state.running else 'false'}")
        cancel_btn.set_visibility(state.running)
        if state.running:
            status.text = (
                f"{i18n.tr('status.running')} — {i18n.tr('tr.stage')}: {state.stage}"
            )
            stage_label.text = (
                f"{state.cur}/{state.total}" if state.total else state.stage
            )
            bar.value = state.pct / 100
        elif state.outcome is not None and not state.reported:
            state.reported = True
            o = state.outcome
            if o.ok:
                status.text = f"{i18n.tr('status.finished')} ({o.elapsed_s}s)"
                dot.style(f"background:{_DOT_IDLE}")
                bar.value = 1.0
                docs.append((pdf_path.get("name", "PDF"), i18n.tr("tr.status_finished")))
                _render_docs()
                for p in o.output_paths:
                    with result_area:
                        ui.label(f"{i18n.tr('tr.result_file')}: {p}").classes("text-sm")
                        ui.download(p, f"{i18n.tr('tr.download')} ({Path(p).name})")
            else:
                status.text = i18n.tr("status.error")
                dot.style(f"background:{_DOT_ERROR}")
                with result_area:
                    ui.label(o.error).classes("wb-err")

    ui.timer(0.5, _poll)
