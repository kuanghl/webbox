"""Chat module page (visual stub)."""

from __future__ import annotations

from ....core import i18n
from ....core.context import AppContext
from ..components import wb_stub_shell


def build(ctx: AppContext) -> None:
    """Render the chat stub page.

    Args:
        ctx: Application context.
    """
    ctx.features.mark_entered("chat")
    wb_stub_shell(
        title=i18n.tr("chat.title_bar"),
        side_label=i18n.tr("chat.conversations").upper(),
        side_items=[],
        empty_icon="chat_bubble_outline",
        placeholder=i18n.tr("chat.placeholder"),
        meta=i18n.tr("chat.meta"),
        new_label=i18n.tr("chat.new"),
        send_label=i18n.tr("common.send"),
    )