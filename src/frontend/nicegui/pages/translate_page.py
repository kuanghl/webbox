"""Translate page: PDF upload, provider options, live progress, results.

The babeldoc pipeline runs as an asyncio task inside the page's event
loop; a ``ui.timer`` polls the shared :class:`TaskState` so the progress
bar updates without blocking the UI (see docs/refer-nicegui.md §3.3).
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
from ..components import on_provider_change, provider_select


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
    """

    running: bool = False
    stage: str = ""
    pct: int = 0
    cur: int = 0
    total: int = 0
    outcome: TranslateOutcome | None = field(default=None)


def build(ctx: AppContext) -> None:
    """Render the translate page content.

    Args:
        ctx: Application context.
    """
    settings = ctx.settings.load()
    state = TaskState()
    pdf_path: dict[str, str] = {}
    task: dict[str, asyncio.Task] = {}

    def _on_upload(e) -> None:
        """Store the uploaded file path (NiceGUI temp file)."""
        pdf_path["path"] = str(e.content.name)
        pdf_path["name"] = e.name
        status.text = f"{i18n.tr('common.file')}: {e.name}"

    with ui.card().classes("w-full"):
        ui.label(i18n.tr("tr.title")).classes("text-lg font-semibold")
        with ui.row().classes("w-full gap-4 items-start"):
            # ---- left: inputs -------------------------------------
            with ui.column().classes("gap-2 min-w-64"):
                ui.upload(
                    auto_upload=True,
                    on_upload=_on_upload,
                ).props("accept=application/pdf").classes("w-full")
                ui.label(i18n.tr("tr.upload_hint")).classes("text-xs text-gray-400")

                lang_in = ui.select(
                    options=TRANSLATE_LANGUAGES,
                    value=DEFAULT_LANG_IN,
                    label=i18n.tr("tr.source_lang"),
                )
                lang_out = ui.select(
                    options=TRANSLATE_LANGUAGES,
                    value=DEFAULT_LANG_OUT,
                    label=i18n.tr("tr.target_lang"),
                )
                model_input = ui.input(label=i18n.tr("tr.model"), value=settings.model)
                url_input = ui.input(label=i18n.tr("tr.base_url"), value=settings.base_url)
                prov = provider_select(
                    settings.provider,
                    on_change=on_provider_change(ctx, model_input, url_input),
                    label=i18n.tr("tr.provider"),
                )
                key_input = ui.input(
                    label=i18n.tr("tr.api_key"),
                    value=settings.api_key,
                    password=True,
                    password_toggle_button=True,
                )
                with ui.row().classes("gap-2"):
                    pages_input = ui.input(label=i18n.tr("tr.pages"), value="").classes("flex-1")
                    qps_input = ui.number(label=i18n.tr("tr.qps"), value=5.0, min=1, step=1).classes("w-24")
                with ui.row().classes("gap-4"):
                    dual = ui.switch(i18n.tr("tr.dual"), value=True)
                    mono = ui.switch(i18n.tr("tr.mono"), value=False)
                out_input = ui.input(label=i18n.tr("tr.output_dir"), value="")

            # ---- right: progress + results ------------------------
            with ui.column().classes("gap-2 flex-1"):
                status = ui.label(i18n.tr("status.idle")).classes("font-medium")
                stage_label = ui.label("").classes("text-sm text-gray-400")
                bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
                with ui.row().classes("gap-2"):
                    start_btn = ui.button(
                        i18n.tr("common.start"), on_click=lambda: start(), icon="play_arrow"
                    ).props("color=primary")
                    cancel_btn = ui.button(
                        i18n.tr("common.cancel"), on_click=lambda: cancel(), icon="stop"
                    ).props("color=negative")
                    cancel_btn.set_visibility(False)
                result_area = ui.column().classes("w-full gap-1")

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
        result_area.clear()
        task["t"] = asyncio.create_task(_worker(job))

    def cancel() -> None:
        """Cancel the in-flight translation task."""
        t = task.get("t")
        if t:
            t.cancel()
            state.running = False
            status.text = i18n.tr("status.cancelled")

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
        elif state.outcome is not None:
            o = state.outcome
            if o.ok:
                status.text = f"{i18n.tr('status.finished')} ({o.elapsed_s}s)"
                bar.value = 1.0
                for p in o.output_paths:
                    with result_area:
                        ui.label(f"{i18n.tr('tr.result_file')}: {p}").classes("text-sm")
                        ui.download(p, f"{i18n.tr('tr.download')} ({Path(p).name})")
            else:
                status.text = i18n.tr("status.error")
                with result_area:
                    ui.label(o.error).classes("text-red-400 text-sm")

    ui.timer(0.5, _poll)
