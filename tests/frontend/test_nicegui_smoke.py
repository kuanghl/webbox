"""NiceGUI smoke test: every page route must render without errors.

Uses NiceGUI's in-process ``user_simulation`` client (no browser needed):
the real page builders run against a throwaway ASGI app and the rendered
element tree is asserted.
"""

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import UserInteraction, user_simulation

from src.core import i18n
from src.core import theme as theme_mod
from src.core.config import AppConfig
from src.core.constants import APP_NAME
from src.core.context import AppContext
from src.frontend.nicegui.pages import (
    home_page,
    settings_page,
    translate_page,
    vram_page,
)


@pytest.fixture()
def ctx(tmp_path) -> AppContext:
    """An AppContext backed by a temporary data/log directory.

    A no-op theme applier is registered so the theme switcher can be exercised
    without pulling NiceGUI's real theme machinery into the test client.
    """
    i18n.set_language("en")
    theme_mod.register_applier("nicegui", lambda name: None)
    return AppContext.create(
        AppConfig(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    )


@pytest.mark.asyncio
async def test_home_page_renders_module_cards(ctx: AppContext) -> None:
    """The home page builds the dock and all module cards."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        await user.should_see(APP_NAME)
        await user.should_see("Translate")
        await user.should_see("VRAM")
        await user.should_see("Settings")


@pytest.mark.asyncio
async def test_translate_page_inputs(ctx: AppContext) -> None:
    """The translate page shows upload, languages and provider controls."""
    async with user_simulation(root=lambda: translate_page.build(ctx)) as user:
        await user.open("/")
        await user.should_see("Drop a PDF here, or click to browse")
        await user.should_see("Source language")
        await user.should_see("Target language")
        await user.should_see("Provider")


@pytest.mark.asyncio
async def test_vram_page_inputs(ctx: AppContext) -> None:
    """The VRAM page shows mode/GPU controls and the estimate button."""
    async with user_simulation(root=lambda: vram_page.build(ctx)) as user:
        await user.open("/")
        await user.should_see("GPU")
        await user.should_see("Estimate")
        await user.should_see("A100 80G")


@pytest.mark.asyncio
async def test_vram_page_estimate_click(ctx: AppContext) -> None:
    """Clicking Estimate renders the result detail rows."""
    async with user_simulation(root=lambda: vram_page.build(ctx)) as user:
        await user.open("/")
        # The top-bar "New Estimate" reset button also matches the content
        # filter, so target the primary button by its exact label.
        buttons = user.find(kind=ui.button, content="Estimate").elements
        btn = next(
            b for b in buttons if b.props.get("label") == i18n.tr("vram.estimate_label")
        )
        UserInteraction(user, {btn}, "Estimate").click()
        await user.should_see("GiB")


@pytest.mark.asyncio
async def test_settings_page_inputs(ctx: AppContext) -> None:
    """The settings page shows provider, theme and user controls."""
    async with user_simulation(root=lambda: settings_page.build(ctx)) as user:
        await user.open("/")
        await user.should_see("Default provider")
        await user.should_see("APPEARANCE")


@pytest.mark.asyncio
async def test_home_page_switchers_visible(ctx: AppContext) -> None:
    """The home dock renders the language/theme/user switchers."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        for marker in ("wb-lang", "wb-theme", "wb-user"):
            assert user.find(marker=marker).elements, f"missing switcher {marker}"


@pytest.mark.asyncio
async def test_home_page_language_switch(ctx: AppContext) -> None:
    """Changing the language switcher persists and switches i18n."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        lang = next(iter(user.find(marker="wb-lang").elements))
        lang.value = "zh"
        assert ctx.settings.load().language == "zh"
        assert i18n.get_language() == "zh"


@pytest.mark.asyncio
async def test_home_page_theme_switch(ctx: AppContext) -> None:
    """Changing the theme switcher persists the theme without a reload."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        theme = next(iter(user.find(marker="wb-theme").elements))
        theme.value = "light"
        assert ctx.settings.load().theme == "light"


@pytest.mark.asyncio
async def test_home_page_user_switch(ctx: AppContext) -> None:
    """Changing the user switcher switches the active user."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        user_select = next(iter(user.find(marker="wb-user").elements))
        user_select.value = "bob"
        assert ctx.settings.active_user() == "bob"


def test_home_page_grid_is_responsive() -> None:
    """The home card grid uses an auto-fit responsive column layout."""
    css = (
        Path(__file__).resolve().parents[2]
        / "src" / "frontend" / "nicegui" / "theme.css"
    ).read_text(encoding="utf-8")
    assert "repeat(auto-fit, minmax(240px, 1fr))" in css


@pytest.mark.asyncio
async def test_home_page_rotating_zone_gated(ctx: AppContext) -> None:
    """The rotating dock is hidden until a feature page has been opened."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        with pytest.raises(AssertionError):
            user.find(marker="wb-rotate")
    # Enter a feature the real way: build its page (no manual mark_entered).
    async with user_simulation(root=lambda: vram_page.build(ctx)) as user:
        await user.open("/")
    assert ctx.features.has_entered("vram")
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
        assert user.find(marker="wb-rotate").elements


