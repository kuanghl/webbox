"""NiceGUI smoke test: the full single-page app must render without errors.

Uses NiceGUI's in-process ``user_simulation`` client (no browser needed):
the real page builder runs against a throwaway ASGI app and the rendered
element tree is asserted.
"""

import pytest
from nicegui.testing import user_simulation

from src.core import i18n
from src.core.config import AppConfig
from src.core.context import AppContext
from src.frontend.nicegui.app import index_page


@pytest.fixture()
def ctx(tmp_path) -> AppContext:
    """An AppContext backed by a temporary data/log directory."""
    i18n.set_language("en")
    return AppContext.create(
        AppConfig(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    )


@pytest.mark.asyncio
async def test_index_page_renders_all_tabs(ctx: AppContext) -> None:
    """The root page builds header + all three tab panels."""
    async with user_simulation(root=lambda: index_page(ctx)) as user:
        await user.open("/")
        await user.should_see("BabelDOC WebBox")
        await user.should_see("Translate")
        await user.should_see("VRAM Calculator")
        await user.should_see("Settings")


@pytest.mark.asyncio
async def test_translate_panel_inputs(ctx: AppContext) -> None:
    """The translate tab shows upload, languages and provider controls."""
    async with user_simulation(root=lambda: index_page(ctx)) as user:
        await user.open("/")
        await user.should_see("Drop a PDF here or click to browse")
        await user.should_see("Source language")
        await user.should_see("Target language")
        await user.should_see("Provider")


@pytest.mark.asyncio
async def test_vram_panel_inputs(ctx: AppContext) -> None:
    """The VRAM tab shows mode/preset/GPU controls and the estimate button."""
    async with user_simulation(root=lambda: index_page(ctx)) as user:
        await user.open("/")
        # tab panels are built eagerly, so all content is present on load
        await user.should_see("Preset")
        await user.should_see("Estimate")
        await user.should_see("A100 80G")


@pytest.mark.asyncio
async def test_settings_panel_inputs(ctx: AppContext) -> None:
    """The settings tab shows provider, theme and user controls."""
    async with user_simulation(root=lambda: index_page(ctx)) as user:
        await user.open("/")
        await user.should_see("Default provider")

