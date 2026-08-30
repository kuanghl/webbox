"""NiceGUI smoke test: every page route must render without errors.

Uses NiceGUI's in-process ``user_simulation`` client (no browser needed):
the real page builders run against a throwaway ASGI app and the rendered
element tree is asserted.
"""

import pytest
from nicegui import ui
from nicegui.testing import UserInteraction, user_simulation

from src.core import i18n
from src.core.config import AppConfig
from src.core.context import AppContext
from src.frontend.nicegui.pages import (
    home_page,
    settings_page,
    translate_page,
    vram_page,
)


@pytest.fixture()
def ctx(tmp_path) -> AppContext:
    """An AppContext backed by a temporary data/log directory."""
    i18n.set_language("en")
    return AppContext.create(
        AppConfig(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    )


@pytest.mark.asyncio
async def test_home_page_renders_module_cards(ctx: AppContext) -> None:
    """The home page builds the dock and all module cards."""
    async with user_simulation(root=lambda: home_page.build(ctx)) as user:
        await user.open("/")
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


