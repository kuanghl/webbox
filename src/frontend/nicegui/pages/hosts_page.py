"""Host/SSH module page (visual stub)."""

from __future__ import annotations

from ....core import i18n
from ....core.context import AppContext
from ..components import wb_stub_shell


def build(ctx: AppContext) -> None:
    """Render the host/SSH stub page.

    Args:
        ctx: Application context.
    """
    ctx.features.mark_entered("hosts")
    wb_stub_shell(
        title=i18n.tr("hosts.title_bar"),
        side_label=i18n.tr("hosts.hosts").upper(),
        side_items=[],
        empty_icon="dns",
        placeholder=i18n.tr("hosts.placeholder"),
        meta=i18n.tr("hosts.meta"),
        new_label=i18n.tr("hosts.new"),
        send_label=i18n.tr("hosts.run"),
    )