"""Reusable NiceGUI layout components for the WebBox dashboard.

Implements the shared chrome of the OpenPencil "webbox" spec: module top
bars, the persistent home dock, sidebars, status strips, panels, chips,
detail rows, stack bars and input bars. Pages compose these pieces inside
their ``build(ctx)`` function (see docs/refer-nicegui.md).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable

from nicegui import ui

from ...core import i18n
from ...core import theme as theme_mod
from ...core.constants import (
    APP_NAME,
    ROUTE_AGENT,
    ROUTE_CHAT,
    ROUTE_HOSTS,
    ROUTE_SETTINGS,
    ROUTE_TRANSLATE,
    ROUTE_VRAM,
    THEMES,
    UI_LANGUAGES,
    USERS,
)
from ...core.context import AppContext
from ...core.store import SettingsStore

__all__ = [
    "MODULES",
    "apply_theme",
    "notify_stub",
    "wb_primary_btn",
    "wb_ghost_btn",
    "wb_top_bar",
    "wb_side_items",
    "wb_status_strip",
    "wb_panel_head",
    "wb_chip",
    "wb_detail_row",
    "wb_stack_bar",
    "wb_legend",
    "wb_input_bar",
    "wb_empty",
    "wb_home_dock",
    "wb_home_card",
    "wb_rotating_zone",
    "wb_switchers",
    "wb_stub_shell",
    "provider_select",
    "on_provider_change",
]

#: Module registry shared by the home dock, cards and rotating zone.
MODULES: list[dict[str, Any]] = [
    {"key": "chat", "icon": "chat_bubble_outline", "color": "#4F8CFF", "route": ROUTE_CHAT},
    {"key": "agent", "icon": "auto_awesome", "color": "#A78BFA", "route": ROUTE_AGENT},
    {"key": "hosts", "icon": "dns", "color": "#3FB950", "route": ROUTE_HOSTS},
    {"key": "translate", "icon": "translate", "color": "#F0883E", "route": ROUTE_TRANSLATE},
    {"key": "vram", "icon": "memory", "color": "#F85149", "route": ROUTE_VRAM},
    {"key": "settings", "icon": "tune", "color": "#8B949E", "route": ROUTE_SETTINGS},
]


def apply_theme(ctx: AppContext, theme_name: str) -> None:
    """Apply the stored theme name to the NiceGUI dark-mode toggle.

    Args:
        ctx: Application context (settings store).
        theme_name: Theme name from the settings store.
    """
    ui.dark_mode(theme_name != "light")


def notify_stub() -> None:
    """Notify that the module has no backend implementation yet."""
    ui.notify(i18n.tr("stub.desc"), type="warning", multi_line=True)


# -- buttons ---------------------------------------------------------------


def wb_primary_btn(
    label: str,
    on_click: Callable | None = None,
    *,
    icon: str | None = None,
    width: int | None = None,
    disabled: bool = False,
) -> ui.button:
    """Primary action button (accent fill, white text).

    Args:
        label: Button label.
        on_click: Click callback.
        icon: Optional Material icon name.
        width: Optional fixed width in px.
        disabled: Initial disabled state.

    Returns:
        The created button.
    """
    btn = ui.button(label, on_click=on_click)
    if icon:
        btn.props(f"icon={icon}")
    btn.classes("wb-btn-primary")
    if width:
        btn.style(f"width:{width}px")
    if disabled:
        btn.disable()
    return btn


def wb_ghost_btn(
    label: str,
    on_click: Callable | None = None,
    *,
    icon: str | None = None,
    width: int | None = None,
    disabled: bool = False,
) -> ui.button:
    """Secondary action button (transparent, bordered).

    Args:
        label: Button label.
        on_click: Click callback.
        icon: Optional Material icon name.
        width: Optional fixed width in px.
        disabled: Initial disabled state.

    Returns:
        The created button.
    """
    btn = ui.button(label, on_click=on_click)
    if icon:
        btn.props(f"icon={icon}")
    btn.classes("wb-btn-ghost")
    if width:
        btn.style(f"width:{width}px")
    if disabled:
        btn.disable()
    return btn


# -- module top bar ---------------------------------------------------------


def wb_top_bar(
    title: str,
    *,
    action_label: str | None = None,
    on_action: Callable | None = None,
    action_icon: str = "add",
    action_disabled: bool = False,
) -> None:
    """Module top bar: back button, title, optional primary action.

    Args:
        title: Module title text.
        action_label: Action button label (None = no action button).
        on_action: Action button callback.
        action_icon: Action button icon.
        action_disabled: Initial disabled state of the action button.
    """
    with ui.row().classes("wb-topbar items-center justify-between no-wrap"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")) \
                .props("flat dense round").classes("wb-back")
            ui.label(title).classes("wb-topbar-title")
        if action_label:
            wb_primary_btn(
                action_label,
                on_action,
                icon=action_icon,
                width=108,
                disabled=action_disabled,
            )


# -- sidebar ----------------------------------------------------------------


def wb_side_items(
    container: ui.column,
    label: str,
    items: list[tuple[str, str]],
    active: int,
    on_select: Callable[[int], None] | None = None,
) -> None:
    """Render a sidebar section: uppercase label + selectable items.

    Re-calling on the same container re-renders the section.

    Args:
        container: NiceGUI column that will be cleared and refilled.
        label: Uppercase section label (e.g. "CONVERSATIONS").
        items: (name, sub) tuples.
        active: Index of the selected item (-1 for none).
        on_select: Callback receiving the selected index.
    """
    container.clear()
    with container:
        ui.label(label).classes("wb-side-label")
        for i, (name, sub) in enumerate(items):
            active_cls = " active" if i == active else ""
            with ui.column().classes(f"wb-side-item{active_cls} gap-1 w-full no-wrap") as item:
                ui.label(name).classes("wb-side-name")
                if sub:
                    ui.label(sub).classes("wb-side-sub")
            if on_select is not None:
                item.on("click", lambda e, i=i: on_select(i))


# -- status strip -----------------------------------------------------------


def wb_status_strip(
    dot_color: str, text: str, meta: str = ""
) -> tuple[ui.element, ui.label, ui.label]:
    """Status strip: colored dot, text, right-aligned meta.

    Args:
        dot_color: CSS color of the status dot.
        text: Primary status text.
        meta: Secondary meta text (right side).

    Returns:
        (dot, text_label, meta_label) for in-place updates.
    """
    with ui.row().classes("wb-status items-center justify-between no-wrap"):
        with ui.row().classes("items-center gap-2.5 no-wrap"):
            dot = ui.element("div").classes("wb-status-dot").style(f"background:{dot_color}")
            text_label = ui.label(text).classes("wb-status-text")
        meta_label = ui.label(meta).classes("wb-status-meta")
    return dot, text_label, meta_label


# -- panels -----------------------------------------------------------------


def wb_chip(text: str, color: str = "") -> ui.label:
    """Small rounded tag (dtype, format, pool size, ...).

    Args:
        text: Chip text.
        color: Optional text color (default: dim).

    Returns:
        The chip label.
    """
    chip = ui.label(text).classes("wb-chip")
    if color:
        chip.style(f"color:{color}")
    return chip


def wb_panel_head(label: str, chip: str = "", chip_color: str = "") -> ui.label | None:
    """Panel header row: uppercase label + optional chip.

    Args:
        label: Uppercase panel label.
        chip: Optional chip text.
        chip_color: Optional chip text color.

    Returns:
        The chip label (for updates) or None.
    """
    with ui.row().classes("wb-panel-head items-center justify-between no-wrap"):
        ui.label(label).classes("wb-panel-label")
        if chip:
            return wb_chip(chip, chip_color)
    return None


def wb_detail_row(label: str, value: str, *, total: bool = False) -> None:
    """Label/value row for estimate breakdowns.

    Args:
        label: Row label.
        value: Row value.
        total: Emphasize as a total row.
    """
    cls = "wb-detail-row items-center justify-between no-wrap"
    if total:
        cls += " total"
    with ui.row().classes(cls):
        ui.label(label).classes("wb-detail-label")
        ui.label(value).classes("wb-detail-value")


def wb_stack_bar(segments: list[tuple[float, str]], *, thin: bool = False) -> None:
    """Horizontal segmented bar.

    Args:
        segments: (percent, color) pairs; percentages need not sum to 100.
        thin: Use the 6px track height.
    """
    with ui.element("div").classes(f"wb-track{' thin' if thin else ''}"):
        for pct, color in segments:
            ui.element("div").classes("wb-fill").style(
                f"width:{max(0.0, min(100.0, pct))}%;background:{color}"
            )


def wb_legend(entries: list[tuple[str, str]]) -> None:
    """Legend row: (color, text) dot+label pairs.

    Args:
        entries: (color, text) tuples.
    """
    with ui.row().classes("items-center gap-3.5 no-wrap flex-wrap"):
        for color, text in entries:
            with ui.row().classes("items-center gap-1.5 no-wrap"):
                ui.element("div").classes("wb-legend-dot").style(f"background:{color}")
                ui.label(text).classes("wb-legend-text")



# -- input bar ---------------------------------------------------------------


@contextmanager
def wb_input_bar():
    """Input bar context: panel-styled footer at the bottom of the page.

    Usage::

        with wb_input_bar():
            with ui.row().classes("wb-inputbox items-center gap-2.5 no-wrap"):
                ...box content...
            with ui.row().classes("items-center justify-between no-wrap"):
                ...action buttons...
    """
    with ui.column().classes("wb-inputbar gap-2.5"):
        yield


# -- empty state --------------------------------------------------------------


def wb_empty(icon: str, title: str, desc: str) -> None:
    """Centered empty/stub state filling the available space.

    Args:
        icon: Material icon name.
        title: Title text.
        desc: Description text.
    """
    with ui.column().classes("wb-empty"):
        ui.icon(icon).classes("wb-empty-icon")
        ui.label(title).classes("wb-empty-title")
        ui.label(desc).classes("wb-empty-desc")


# -- home ---------------------------------------------------------------------


def wb_home_dock(ctx: AppContext) -> None:
    """Persistent top dock: brand, module tiles and the settings switchers.

    The dock is the home page's header. It shows the app brand on the left,
    the module tiles in the centre and the language/theme/user switchers on
    the right (see ``wb_switchers``). Each tile is a rounded square with the
    module icon; clicking navigates to the module route.

    Args:
        ctx: Application context (drives the language/theme/user switchers).
    """
    with ui.row().classes("wb-dock items-center gap-3.5 no-wrap"):
        ui.label(APP_NAME).classes("wb-dock-brand")
        with ui.row().classes("wb-dock-tiles items-center gap-3.5 no-wrap"):
            for m in MODULES:
                with ui.element("div").classes("wb-dock-tile") as tile:
                    ui.icon(m["icon"]).style(f"color:{m['color']};font-size:24px")
                tile.tooltip(i18n.tr(f"home.card.{m['key']}.name"))
                tile.on("click", lambda e, r=m["route"]: ui.navigate.to(r))
        with ui.row().classes("wb-switchers items-center gap-2 no-wrap"):
            wb_switchers(ctx)


def wb_home_card(m: dict[str, Any]) -> None:
    """Home module card: icon, name, description, Open button.

    Args:
        m: Module entry from :data:`MODULES`.
    """
    key, route, color = m["key"], m["route"], m["color"]
    with ui.column().classes("wb-home-card") as card:
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            with ui.element("div").classes("wb-home-icon").style(f"background:{color}22"):
                ui.icon(m["icon"]).style(f"color:{color};font-size:24px")
            with ui.element("div").classes("wb-open-btn"):
                ui.label(i18n.tr("home.open"))
        ui.label(i18n.tr(f"home.card.{key}.name")).classes("wb-home-card-name")
        ui.label(i18n.tr(f"home.card.{key}.desc")).classes("wb-home-card-desc")
        card.on("click", lambda e: ui.navigate.to(route))


def wb_rotating_zone() -> None:
    """Bottom carousel strip with mini module tiles."""
    with ui.row().classes("wb-rotate items-center gap-3 no-wrap").mark("wb-rotate"):
        ui.element("div").classes("wb-pullbar")
        for m in MODULES:
            with ui.column().classes("wb-mid-tile") as tile:
                ui.icon(m["icon"]).style(f"color:{m['color']};font-size:20px")
                ui.label(i18n.tr(f"home.card.{m['key']}.name")).classes("wb-mid-title")
            tile.on("click", lambda e, r=m["route"]: ui.navigate.to(r))
        ui.label(i18n.tr("home.rotate.hint")).classes("wb-rotate-hint")
        ui.element("div").classes("wb-pullbar")


# -- switchers (language / theme / user) -------------------------------------


def wb_switchers(ctx: AppContext) -> None:
    """Render the language, theme and user switcher selects.

    Language and user changes persist and reload the page (labels render from
    i18n keys at build time); theme applies live via the core applier.

    Args:
        ctx: Application context.
    """
    settings = ctx.settings.load()

    def switch_language(e) -> None:
        s = ctx.settings.load()
        s.language = e.value
        ctx.settings.save(s)
        i18n.set_language(s.language)
        ui.navigate.reload()

    ui.select(
        options=UI_LANGUAGES, value=settings.language, on_change=switch_language,
        with_input=False,
    ).classes("w-28").props("dense outlined").mark("wb-lang")

    def switch_theme(e) -> None:
        s = ctx.settings.load()
        s.theme = e.value
        ctx.settings.save(s)
        theme_mod.apply("nicegui", e.value)
        ui.notify(i18n.tr("st.theme_applied"), type="positive")

    ui.select(
        options=THEMES, value=settings.theme, on_change=switch_theme,
        with_input=False,
    ).classes("w-24").props("dense outlined").mark("wb-theme")

    def switch_user(e) -> None:
        ctx.settings.set_active_user(e.value)
        ui.notify(i18n.tr("st.user_switched", user=e.value), type="positive")
        ui.navigate.reload()

    ui.select(
        options=list(USERS), value=settings.user, on_change=switch_user,
        with_input=False,
    ).classes("w-24").props("dense outlined").mark("wb-user")


# -- stub module shell --------------------------------------------------------


def wb_stub_shell(
    *,
    title: str,
    side_label: str,
    side_items: list[tuple[str, str]],
    empty_icon: str,
    placeholder: str,
    meta: str = "",
    new_label: str | None = None,
    send_label: str | None = None,
) -> None:
    """Full stub module page: top bar, sidebar, empty state, input bar.

    Args:
        title: Module title for the top bar.
        side_label: Uppercase sidebar section label.
        side_items: (name, sub) sidebar entries.
        empty_icon: Material icon for the empty state.
        placeholder: Input bar placeholder text.
        meta: Optional meta text inside the input box.
        new_label: Optional top-bar action label (notifies the stub notice).
        send_label: Optional input-bar primary button label.
    """
    with ui.column().classes("wb-page w-full"):
        wb_top_bar(title, action_label=new_label, on_action=notify_stub)
        with ui.row().classes("wb-body"):
            with ui.column().classes("wb-sidebar gap-2") as side:
                wb_side_items(side, side_label, side_items, -1)
            with ui.column().classes("wb-main"):
                wb_empty(empty_icon, i18n.tr("stub.title"), i18n.tr("stub.desc"))
        with wb_input_bar():
            with ui.row().classes("wb-inputbox items-center gap-2.5 no-wrap w-full"):
                ui.input(placeholder=placeholder).props("dense flat").classes("flex-1")
                if meta:
                    ui.label(meta).classes("wb-inputbox-hint")
                if send_label:
                    wb_primary_btn(send_label, on_click=notify_stub, icon="send")


# -- provider helpers (translate / settings pages) ----------------------------


def provider_select(
    value: str, on_change=None, classes: str = "w-44", label: str | None = None
) -> ui.select:
    """Build a provider dropdown pre-filled with known providers.

    Args:
        value: Currently selected provider name.
        on_change: Optional change callback.
        classes: CSS classes for sizing.
        label: Optional field label.

    Returns:
        The configured select element.
    """
    from ...core.store import PROVIDER_DEFAULTS

    return ui.select(
        options=list(PROVIDER_DEFAULTS.keys()),
        value=value,
        label=label,
        on_change=on_change,
        with_input=False,
    ).classes(classes)


def on_provider_change(ctx: AppContext, model_input: ui.input, url_input: ui.input):
    """Return a change handler that fills model/URL defaults for a provider.

    Args:
        ctx: Application context (unused, kept for signature symmetry).
        model_input: Model name input to update.
        url_input: Base URL input to update.

    Returns:
        A callback suitable for ``ui.select(on_change=...)``.
    """

    def handler(e) -> None:
        model, url = SettingsStore.provider_defaults(e.value)
        if model:
            model_input.value = model
        if url:
            url_input.value = url

    return handler

