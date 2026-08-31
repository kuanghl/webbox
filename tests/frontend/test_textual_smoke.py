"""Textual smoke tests for the WebBox TUI (headless, no terminal needed).

Uses ``App.run_test``: the real app composes, tabs switch, the VRAM
estimate renders, translate validation and the worker error path run,
and a settings save rebuilds the UI. A temporary data dir keeps real
user files untouched; no network or babeldoc run is needed.
"""

import asyncio
import time
from collections.abc import Callable

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, Select, Static, TabbedContent

from src.core import i18n
from src.core.config import AppConfig
from src.core.context import AppContext
from src.frontend.textual.app import SwitcherBar, WebboxApp
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


async def _wait_for(
    pilot: Pilot, condition: Callable[[], bool], *, what: str, timeout: float = 5.0
) -> None:
    """Poll until ``condition()`` is true so async app work can settle.

    Args:
        pilot: The Textual test pilot.
        condition: Zero-arg callable returning True once settled.
        what: Description used in the failure message.
        timeout: Maximum seconds to wait before failing.

    Raises:
        AssertionError: If the condition is not met within ``timeout``.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"Timed out waiting for {what}")


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


@pytest.mark.asyncio
async def test_switcher_bar_present_with_initial_values(ctx: AppContext) -> None:
    """The header bar renders language/theme/user selects seeded from settings."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        app = pilot.app
        assert app.query_one(SwitcherBar)
        assert app.query_one("#sw_lang", Select).value == "en"
        assert app.query_one("#sw_theme", Select).value == "dark"
        assert app.query_one("#sw_user", Select).value == "alice"
        # Each select is preceded by its translated label.
        for select_id in ("sw_lang", "sw_theme", "sw_user"):
            assert app.query_one(f"#lbl_{select_id}", Static)


@pytest.mark.asyncio
async def test_switcher_language_change(ctx: AppContext) -> None:
    """Changing the header language persists, retranslates and rebuilds."""
    async with WebboxApp(ctx).run_test(size=SIZE) as pilot:
        await pilot.pause()
        app = pilot.app
        original_settings = app.query_one(SettingsPage)
        app.query_one("#sw_lang", Select).value = "zh"
        # The settings pane is rebuilt last, so a fresh SettingsPage means
        # the whole rebuild finished before the app is torn down.
        await _wait_for(
            pilot,
            lambda: (
                "界面语言" in str(app.query_one("#lbl_sw_lang", Static).render())
                and app.query_one(SettingsPage) is not original_settings
            ),
            what="switcher labels retranslated and pages rebuilt",
        )
        assert ctx.settings.load().language == "zh"
        assert i18n.get_language() == "zh"
        tabs = app.query_one(TabbedContent)
        assert tabs.get_tab("pane_translate").label_text == "翻译"


@pytest.mark.asyncio
async def test_switcher_theme_change(ctx: AppContext) -> None:
    """Changing the header theme persists and applies live with a notice."""
    async with WebboxApp(ctx).run_test(size=SIZE, notifications=True) as pilot:
        await pilot.pause()
        app = pilot.app
        app.query_one("#sw_theme", Select).value = "light"
        await _wait_for(
            pilot, lambda: app.theme == "textual-light", what="theme applied"
        )
        assert ctx.settings.load().theme == "light"
        messages = [n.message for n in app._notifications]
        assert any("Theme applied" in m for m in messages)


@pytest.mark.asyncio
async def test_switcher_user_change(ctx: AppContext) -> None:
    """Switching user loads that user's settings and rebuilds the UI."""
    bob = ctx.settings.load("bob")
    bob.language = "zh"
    bob.theme = "light"
    ctx.settings.save(bob)
    async with WebboxApp(ctx).run_test(size=SIZE, notifications=True) as pilot:
        await pilot.pause()
        app = pilot.app
        app.query_one("#sw_user", Select).value = "bob"
        await _wait_for(
            pilot,
            lambda: (
                app.query_one("#sw_lang", Select).value == "zh"
                and app.query_one("#sw_theme", Select).value == "light"
                and app.query_one("#sw_user", Select).value == "bob"
            ),
            what="switchers synced to bob",
        )
        assert ctx.settings.active_user() == "bob"
        assert ctx.settings.load().language == "zh"
        assert ctx.settings.load().theme == "light"
        assert app.theme == "textual-light"
        assert i18n.get_language() == "zh"
        tabs = app.query_one(TabbedContent)
        assert tabs.get_tab("pane_translate").label_text == "翻译"
        messages = [n.message for n in app._notifications]
        assert any("Switched to user bob" in m for m in messages)
