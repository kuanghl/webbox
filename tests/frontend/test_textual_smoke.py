"""Textual smoke tests for the WebBox TUI (headless, no terminal needed).

Uses ``App.run_test``: the real app composes, tabs switch, the VRAM
estimate renders, translate validation and the worker error path run,
and a settings save rebuilds the UI. A temporary data dir keeps real
user files untouched; no network or babeldoc run is needed.
"""

import asyncio

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, Select, Static, TabbedContent

from src.core import i18n
from src.core.config import AppConfig
from src.core.context import AppContext
from src.frontend.textual.app import WebboxApp
from src.frontend.textual.pages.settings import SettingsPage
from src.frontend.textual.pages.translate import TranslatePage
from src.frontend.textual.pages.vram import VramPage
from src.modules.translate.interfaces import (
    ProgressEvent,
    TranslateOutcome,
    TranslateStage,
)

SIZE = (100, 60)  # tall enough for every tab's form to be visible


@pytest.fixture()
def ctx(tmp_path) -> AppContext:
    """An AppContext backed by a temporary data/log directory."""
    i18n.set_language("en")
    return AppContext.create(
        AppConfig(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    )


@pytest.mark.asyncio
async def test_app_composes_all_tabs(ctx: AppContext) -> None:
    """All three tabs exist with translated labels."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        app = pilot.app
        assert app.query_one(TranslatePage)
        assert app.query_one(VramPage)
        assert app.query_one(SettingsPage)
        tabs = app.query_one(TabbedContent)
        assert tabs.get_tab("pane_translate").label_text == "Translate"
        assert tabs.get_tab("pane_vram").label_text == "VRAM Calculator"
        assert tabs.get_tab("pane_settings").label_text == "Settings"


async def _click_tab(pilot: Pilot, pane_id: str) -> None:
    """Click a tab in the tab bar (tab ids are prefixed by Textual)."""
    await pilot.click(f"#--content-tab-{pane_id}")
    await pilot.pause()


@pytest.mark.asyncio
async def test_tab_switching(ctx: AppContext) -> None:
    """Clicking tabs moves the active pane like the NiceGUI tab bar."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        tabs = pilot.app.query_one(TabbedContent)
        await _click_tab(pilot, "pane_vram")
        assert tabs.active == "pane_vram"
        await _click_tab(pilot, "pane_settings")
        assert tabs.active == "pane_settings"


@pytest.mark.asyncio
async def test_vram_estimate_renders_breakdown(ctx: AppContext) -> None:
    """The estimate button renders total, bar and breakdown table."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        await _click_tab(pilot, "pane_vram")
        await pilot.click("#btn_estimate")
        await pilot.pause()
        app = pilot.app
        # Static.render() returns rich Content; compare its plain text.
        assert "GiB" in str(app.query_one("#vram_total", Static).render())
        assert app.query_one("#breakdown").row_count > 0


@pytest.mark.asyncio
async def test_translate_requires_file(ctx: AppContext) -> None:
    """Starting without a PDF path notifies instead of running."""
    async with WebboxApp(ctx).run_test(size=SIZE, notifications=True) as pilot:
        await pilot.pause()
        await pilot.click("#btn_start")
        await pilot.pause()
        messages = [n.message for n in pilot.app._notifications]
        assert any("PDF file" in m for m in messages)


@pytest.mark.asyncio
async def test_translate_worker_reports_error(ctx: AppContext, tmp_path) -> None:
    """A missing PDF runs the worker and renders the error result."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        page = pilot.app.query_one(TranslatePage)
        page.query_one("#pdf_path", Input).value = str(tmp_path / "missing.pdf")
        page.query_one("#api_key", Input).value = "test-key"
        await pilot.click("#btn_start")
        result = page.query_one("#result", Static)
        for _ in range(200):
            await pilot.pause(0.05)
            if result.render():
                break
        # Static.render() returns rich Content; compare its plain text.
        assert "missing.pdf" in str(result.render())


class _SlowTranslate:
    """Duck-typed stand-in for the translate service that stalls mid-job."""

    async def run(self, job):
        """Yield one progress event, stall, then succeed."""
        yield ProgressEvent(
            stage=TranslateStage.PARSING,
            page=1,
            total_pages=10,
            message="Parsing",
            overall_pct=10,
        )
        await asyncio.sleep(30)
        yield TranslateOutcome(ok=True, output_paths=("/tmp/out.pdf",), elapsed_s=1.0)


@pytest.mark.asyncio
async def test_translate_provider_defaults_fill(ctx: AppContext) -> None:
    """Picking a provider fills the model/base_url defaults in the form."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        page = pilot.app.query_one(TranslatePage)
        page.query_one("#provider", Select).value = "DeepSeek"
        await pilot.pause()
        assert page.query_one("#model", Input).value == "deepseek-chat"
        assert page.query_one("#base_url", Input).value == "https://api.deepseek.com/v1"


@pytest.mark.asyncio
async def test_vram_serving_mode_renders_vllm(ctx: AppContext) -> None:
    """Serving mode toggles the mode boxes and renders the vLLM command."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        await _click_tab(pilot, "pane_vram")
        page = pilot.app.query_one(VramPage)
        page.query_one("#mode", Select).value = "serving"
        await pilot.pause()
        assert page.query_one("#serve_box").styles.display == "block"
        assert page.query_one("#train_box").styles.display == "none"
        await pilot.click("#btn_estimate")
        await pilot.pause()
        assert "vllm serve" in str(page.query_one("#vllm_cmd", Static).render())
        page.query_one("#mode", Select).value = "training"
        await pilot.pause()
        assert page.query_one("#train_box").styles.display == "block"
        assert page.query_one("#serve_box").styles.display == "none"


@pytest.mark.asyncio
async def test_translate_progress_and_cancel(ctx: AppContext) -> None:
    """A running job renders progress; Cancel stops it and says so."""
    ctx.translate = _SlowTranslate()
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        page = pilot.app.query_one(TranslatePage)
        page.query_one("#pdf_path", Input).value = "doc.pdf"
        page.query_one("#api_key", Input).value = "k"
        await pilot.click("#btn_start")
        status = page.query_one("#status", Static)
        for _ in range(100):
            await pilot.pause(0.05)
            if "Running" in str(status.render()):
                break
        assert "Running" in str(status.render())
        assert str(page.query_one("#stage", Static).render()) == "1/10"
        await pilot.click("#btn_cancel")
        for _ in range(100):
            await pilot.pause(0.05)
            if "Cancelled" in str(status.render()):
                break
        assert "Cancelled" in str(status.render())


@pytest.mark.asyncio
async def test_settings_save_switches_language(ctx: AppContext) -> None:
    """Saving with a new language re-translates tabs and rebuilds pages."""
    async with WebboxApp(ctx).run_test(size=SIZE, notifications=True) as pilot:
        await pilot.pause()
        await _click_tab(pilot, "pane_settings")
        page = pilot.app.query_one(SettingsPage)
        page.query_one("#lang", Select).value = "zh"
        await pilot.pause()
        await pilot.click("#btn_save")
        await pilot.pause()
        tabs = pilot.app.query_one(TabbedContent)
        assert tabs.get_tab("pane_translate").label_text == "翻译"
        # The rebuilt settings page reads the saved values back.
        assert pilot.app.query_one(SettingsPage).query_one("#lang", Select).value == "zh"
        messages = [n.message for n in pilot.app._notifications]
        assert any("设置已保存" in m for m in messages)
