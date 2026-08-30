"""VRAM page: mode/model/GPU/precision inputs, breakdown, vLLM command.

Estimation is pure CPU math, so it runs synchronously in the click
handler; only the optional HuggingFace fetch for custom models is async
(see docs/refer-nicegui.md §3.3).
"""

from __future__ import annotations

from nicegui import ui

from ....core import i18n
from ....core.context import AppContext
from ....modules.vram.models import (
    DTYPE_BYTES,
    GPU_SPECS,
    MODEL_PRESETS,
    OPTIMIZER_BYTES,
    VramEstimate,
    VramRequest,
)
from ....modules.vram.service import VramService

_MODES = ["inference", "training", "serving"]


def build(ctx: AppContext) -> None:
    """Render the VRAM page content.

    Args:
        ctx: Application context (provides the vram service).
    """
    service: VramService = ctx.vram
    result_box = ui.column().classes("w-full gap-2")

    with ui.card().classes("w-full"):
        ui.label(i18n.tr("vram.title")).classes("text-lg font-semibold")
        with ui.row().classes("w-full gap-4 items-start"):
            # ---- left: inputs -------------------------------------
            with ui.column().classes("gap-2 min-w-64"):
                mode = ui.select(
                    options=_MODES, value="inference", label=i18n.tr("vram.mode")
                )
                preset = ui.select(
                    options=["custom", *MODEL_PRESETS.keys()],
                    value="Qwen2.5-7B",
                    label=i18n.tr("vram.preset"),
                )
                manual_box = ui.column().classes("gap-1")
                with manual_box:
                    ui.label(i18n.tr("vram.custom")).classes("text-sm font-medium")
                    with ui.row().classes("gap-2"):
                        m_params = ui.number(
                            label=i18n.tr("vram.params_b"), value=0, step=0.1
                        ).classes("flex-1")
                        m_hidden = ui.number(
                            label=i18n.tr("vram.hidden"), value=0, step=64
                        ).classes("flex-1")
                    with ui.row().classes("gap-2"):
                        m_layers = ui.number(
                            label=i18n.tr("vram.layers"), value=0, step=1
                        ).classes("flex-1")
                        m_heads = ui.number(
                            label=i18n.tr("vram.heads"), value=0, step=1
                        ).classes("flex-1")
                    with ui.row().classes("gap-2"):
                        m_kv_heads = ui.number(
                            label=i18n.tr("vram.kv_heads"), value=0, step=1
                        ).classes("flex-1")
                        m_vocab = ui.number(
                            label=i18n.tr("vram.vocab"), value=0, step=1000
                        ).classes("flex-1")
                    m_inter = ui.number(
                        label=i18n.tr("vram.intermediate"), value=0, step=64
                    ).classes("w-full")
                manual_box.set_visibility(False)

                gpu = ui.select(
                    options=list(GPU_SPECS.keys()),
                    value="A100 80G",
                    label=i18n.tr("vram.gpu"),
                )
                dtype = ui.select(
                    options=list(DTYPE_BYTES.keys()),
                    value="BF16",
                    label=i18n.tr("vram.dtype"),
                )
                with ui.row().classes("gap-2"):
                    batch = ui.number(
                        label=i18n.tr("vram.batch"), value=1, min=1, step=1
                    ).classes("flex-1")
                    seq = ui.number(
                        label=i18n.tr("vram.seq_len"), value=2048, min=1, step=512
                    ).classes("flex-1")

                train_box = ui.column().classes("gap-1")
                with train_box:
                    lora = ui.switch(i18n.tr("vram.lora"), value=True)
                    lora_rank = ui.number(
                        label=i18n.tr("vram.lora_rank"), value=8, min=1, step=8
                    ).classes("w-32")
                    optimizer = ui.select(
                        options=list(OPTIMIZER_BYTES.keys()),
                        value="AdamW (32-bit)",
                        label=i18n.tr("vram.optimizer"),
                    ).classes("w-44")
                    grad_ckpt = ui.switch(i18n.tr("vram.grad_ckpt"), value=True)
                    ddp = ui.switch(i18n.tr("vram.ddp"), value=False)
                    mixed = ui.switch(i18n.tr("vram.mixed_precision"), value=True)

                serve_box = ui.column().classes("gap-1")
                with serve_box:
                    num_gpus = ui.number(
                        label=i18n.tr("vram.num_gpus"), value=1, min=1, step=1
                    ).classes("w-32")
                    max_len = ui.number(
                        label=i18n.tr("vram.max_model_len"), value=4096, min=1, step=512
                    ).classes("w-44")
                    max_seqs = ui.number(
                        label=i18n.tr("vram.max_num_seqs"), value=16, min=1, step=1
                    ).classes("w-44")
                    mem_util = ui.slider(
                        min=0.5, max=0.95, step=0.05, value=0.9
                    ).classes("w-44")
                    kv_dtype = ui.select(
                        options=["auto", "fp8"],
                        value="auto",
                        label=i18n.tr("vram.kv_dtype"),
                    ).classes("w-32")
                    cuda_graphs = ui.switch(i18n.tr("vram.cuda_graphs"), value=True)

                def _sync_boxes() -> None:
                    m = mode.value
                    train_box.set_visibility(m == "training")
                    serve_box.set_visibility(m == "serving")
                    manual_box.set_visibility(preset.value == "custom")

                mode.on_value_change(lambda _: _sync_boxes())
                preset.on_value_change(lambda _: _sync_boxes())

                with ui.row().classes("gap-2"):
                    ui.button(
                        i18n.tr("vram.estimate"),
                        on_click=lambda: estimate(),
                        icon="calculate",
                    ).props("color=primary")
                    ui.button(
                        i18n.tr("vram.fetch_hf"),
                        on_click=lambda: fetch_hf(),
                        icon="cloud_download",
                    )

            # ---- right: results ------------------------------------
            with ui.column().classes("gap-2 flex-1"):
                result_box

    def _collect_request() -> VramRequest:
        """Assemble a VramRequest from the form widgets."""
        return VramRequest(
            model_id="" if preset.value == "custom" else preset.value,
            gpu=gpu.value,
            mode=mode.value,
            dtype=dtype.value,
            batch_size=int(batch.value or 1),
            seq_length=int(seq.value or 1),
            manual_params_b=float(m_params.value or 0),
            manual_hidden=int(m_hidden.value or 0),
            manual_layers=int(m_layers.value or 0),
            manual_heads=int(m_heads.value or 0),
            manual_kv_heads=int(m_kv_heads.value or 0),
            manual_vocab=int(m_vocab.value or 0),
            manual_intermediate=int(m_inter.value or 0),
            lora=bool(lora.value),
            lora_rank=int(lora_rank.value or 8),
            optimizer=optimizer.value,
            gradient_checkpointing=bool(grad_ckpt.value),
            ddp=bool(ddp.value),
            mixed_precision=bool(mixed.value),
            num_gpus=int(num_gpus.value or 1),
            max_model_len=int(max_len.value or 4096),
            max_num_seqs=int(max_seqs.value or 16),
            gpu_memory_utilization=float(mem_util.value or 0.9),
            kv_cache_dtype=kv_dtype.value,
            cuda_graphs=bool(cuda_graphs.value),
        )

    def render_result(est: VramEstimate) -> None:
        """Draw the estimate into the result column."""
        result_box.clear()
        with result_box:
            with ui.row().classes("items-center gap-3"):
                ui.label(
                    f"{i18n.tr('vram.total')}: {est.total_gb} GiB"
                ).classes("text-lg font-semibold")
                fit = est.fits
                badge = ui.label(
                    i18n.tr("vram.fits" if fit else "vram.not_fits")
                ).props(f"color={'positive' if fit else 'negative'}").classes("text-sm font-bold")
            ui.linear_progress(
                value=est.utilization_pct / 100, show_value=True
            ).classes("w-full")
            ui.label(
                f"{i18n.tr('vram.utilization')}: {est.utilization_pct}%  "
                f"{i18n.tr('vram.headroom')}: {est.headroom_gb} GiB "
                f"({gpu.value}, {est.gpu_vram_gb} GiB)"
            ).classes("text-sm text-gray-400")

            with ui.expansion(i18n.tr("vram.breakdown"), icon="table").classes("w-full"):
                with ui.table(
                    rows=[
                        {"item": i18n.tr(it.key), "gb": f"{it.gb:.2f}"}
                        for it in est.items
                    ],
                    columns=[
                        {"name": "item", "label": i18n.tr("common.details"), "field": "item"},
                        {"name": "gb", "label": "GiB", "field": "gb", "align": "right"},
                    ],
                    row_key="item",
                ).classes("w-full"):
                    pass

            if est.vllm_command:
                with ui.expansion(i18n.tr("vram.vllm_cmd"), icon="terminal").classes("w-full"):
                    ui.label(
                        f"{i18n.tr('vram.max_seqs')}: {est.max_seqs}   "
                        f"{i18n.tr('vram.kv_per_token')}: {est.kv_per_token_kb:.1f} KB   "
                        f"{i18n.tr('vram.kv_per_seq')}: {est.kv_per_seq_gb:.2f} GiB"
                    ).classes("text-sm")
                    ui.label(
                        f"{i18n.tr('vram.prompt_tps')}: {est.prompt_tps:,.0f} tok/s   "
                        f"{i18n.tr('vram.gen_tps')}: {est.gen_tps:,.0f} tok/s"
                    ).classes("text-sm text-gray-400")
                    with ui.row().classes("items-center gap-2"):
                        ui.code(est.vllm_command).classes("flex-1 text-xs")
                        ui.button(
                            icon="content_copy",
                            on_click=lambda: (
                                ui.run_javascript(
                                    f"navigator.clipboard.writeText({est.vllm_command!r})"
                                ),
                                ui.notify(i18n.tr("common.copied")),
                            ),
                        ).props("flat dense")

            if est.notes:
                with ui.expansion(i18n.tr("vram.notes"), icon="info").classes("w-full"):
                    for note in est.notes:
                        ui.label(f"• {note}").classes("text-sm")

    def estimate() -> None:
        """Run the (synchronous) estimation and render the result."""
        try:
            render_result(service.estimate(_collect_request()))
        except ValueError as exc:
            ui.notify(str(exc), type="warning")

    async def fetch_hf() -> None:
        """Fetch a HuggingFace config and fill the manual model fields."""
        model_id = preset.value
        if model_id == "custom" and not any(
            (m_params.value, m_hidden.value, m_layers.value)
        ):
            ui.notify(i18n.tr("vram.need_manual"), type="warning")
            return
        ui.notify("Fetching config…", type="info")
        config = await service.fetch_model_config(model_id)
        if config is None:
            ui.notify(i18n.tr("vram.fetch_failed"), type="negative")
            return
        params = VramService.estimate_params(config)
        if params:
            m_params.value = params
        m_hidden.value = config.get("hidden_size", 0) or 0
        m_layers.value = config.get("num_hidden_layers", 0) or 0
        m_heads.value = config.get("num_attention_heads", 0) or 0
        m_kv_heads.value = config.get("num_key_value_heads", 0) or 0
        m_vocab.value = config.get("vocab_size", 0) or 0
        m_inter.value = config.get("intermediate_size", 0) or 0
        ui.notify(i18n.tr("common.saved"), type="positive")
