"""Agent/ACP module page (visual stub)."""

from __future__ import annotations

from ....core import i18n
from ....core.context import AppContext
from ..components import wb_stub_shell


def build(ctx: AppContext) -> None:
    """Render the agent stub page.

    Args:
        ctx: Application context.
    """
    ctx.features.mark_entered("agent")
    wb_stub_shell(
        title=i18n.tr("agent.title_bar"),
        side_label=i18n.tr("agent.agents").upper(),
        side_items=[],
        empty_icon="smart_toy",
        placeholder=i18n.tr("agent.placeholder"),
        meta=i18n.tr("agent.meta"),
        new_label=i18n.tr("agent.new"),
        send_label=i18n.tr("common.send"),
    )