"""VRAM page: mode/model/GPU/precision inputs, breakdown, vLLM command.

OpenPencil-style layout: top bar, model sidebar, status strip,
PARAMETERS/ESTIMATE panels and a bottom action bar. Estimation is pure
CPU math, so it runs synchronously in the click handler; only the
optional HuggingFace fetch for custom models is async (see
docs/refer-nicegui.md §3.3).
"""

from __future__ import annotations

from nicegui import ui

from ....core import i18n
from ....core.context import AppContext
from ....modules.vram.models import (
    DTYPE_BYTES,
    GPU_SPECS,
    ITEM_ACTIVATIONS,
    ITEM_COMPILE,
    ITEM_CUDA,
    ITEM_DDP,
    ITEM_GRADIENTS,
    ITEM_KV_CACHE,
    ITEM_OVERHEAD,
    ITEM_OPTIMIZER,
    ITEM_WEIGHTS,
    MODEL_PRESETS,
    OPTIMIZER_BYTES,
    VramEstimate,
    VramRequest,
)
from ....modules.vram.service import VramService
from ..components import (
    wb_detail_row,
    wb_ghost_btn,
    wb_input_bar,
    wb_legend,
    wb_panel_head,
    wb_primary_btn,
    wb_side_items,
    wb_stack_bar,
    wb_status_strip,
    wb_top_bar,
)

_MODES = ["inference", "training", "serving"]

#: Sidebar order: presets first, custom last.
_MODEL_OPTIONS = [*MODEL_PRESETS.keys(), "custom"]

#: Stack-bar segment and legend colors per breakdown item.
_ITEM_COLORS = {
    ITEM_WEIGHTS: "#6d8dff",
    ITEM_KV_CACHE: "#34d399",
    ITEM_ACTIVATIONS: "#fbbf24",
    ITEM_GRADIENTS: "#f87171",
    ITEM_OPTIMIZER: "#a78bfa",
    ITEM_DDP: "#f0883e",
    ITEM_COMPILE: "#22d3ee",
    ITEM_CUDA: "#e879f9",
    ITEM_OVERHEAD: "#71717a",
}

#: Short legend label (i18n key) per breakdown item.
_ITEM_LEGEND = {
    ITEM_WEIGHTS: "vram.leg.weights",
    ITEM_KV_CACHE: "vram.leg.kv",
    ITEM_ACTIVATIONS: "vram.leg.act",
    ITEM_GRADIENTS: "vram.leg.grad",
    ITEM_OPTIMIZER: "vram.leg.optim",
    ITEM_DDP: "vram.leg.ddp",
    ITEM_COMPILE: "vram.leg.compile",
    ITEM_CUDA: "vram.leg.cuda",
    ITEM_OVERHEAD: "vram.leg.overhead",
}

_DOT_IDLE = "#71717a"
_DOT_FIT = "#34d399"
_DOT_OVER = "#fbbf24"
_DOT_ERROR = "#f87171"


def build(ctx: AppContext) -> None:
    """Render the VRAM page.

    Args:
        ctx: Application context (provides the vram service).
    """
    ctx.features.mark_entered("vram")
    service: VramService = ctx.vram
    model_state: dict[str, str] = {"value": "Qwen2.5-7B"}
    result_area = ui.column().classes("w-full gap-2")

    def _model_items() -> list[tuple[str, str]]:
        """Sidebar entries: presets with param count, then custom."""
        items = [(name, f"{MODEL_PRESETS[name].params_b:g}B") for name in MODEL_PRESETS]
        items.append((i18n.tr("vram.custom"), ""))
        return items

    def _render_models() -> None:
        """Re-render the model sidebar with the current selection."""
        side.clear()
        wb_side_items(
            side,
            i18n.tr("vram.models").upper(),
            _model_items(),
            _MODEL_OPTIONS.index(model_state["value"]),
            _select_model,
        )

    def _model_hint() -> str:
        """Input-bar hint describing the selected model."""
        name = model_state["value"]
        if name == "custom":
            return i18n.tr("vram.custom")
        spec = MODEL_PRESETS[name]
        return f"{name} · {spec.params_b:g}B · {spec.layers}L"

    def _select_model(idx: int) -> None:
        """Pick a model from the sidebar."""
        model_state["value"] = _MODEL_OPTIONS[idx]
        model_hint.text = _model_hint()
        _sync_boxes()
        _render_models()

    def _sync_boxes() -> None:
        """Show/hide mode- and model-dependent input groups."""
        train_box.set_visibility(mode.value == "training")
        serve_box.set_visibility(mode.value == "serving")
        manual_box.set_visibility(model_state["value"] == "custom")

    def _gpu_count() -> int:
        """Effective GPU count for the current mode."""
        return int(num_gpus.value or 1) if mode.value == "serving" else 1

    def _pool_meta() -> str:
        """Pool description shown in the status strip meta."""
        return i18n.tr(
            "vram.pool_meta",
            n=_gpu_count(),
            gpu=gpu.value,
            gb=GPU_SPECS[gpu.value].vram_gb * _gpu_count(),
        )

    def _refresh_meta() -> None:
        """Update the status strip meta after a pool-affecting change."""
        status_meta.text = _pool_meta()

    def reset() -> None:
        """Clear the last estimate for a fresh run."""
        result_area.clear()
        if est_chip is not None:
            est_chip.visible = False
        dot.style(f"background:{_DOT_IDLE}")
        status.text = i18n.tr("vram.estimate_label")
        _refresh_meta()

    with ui.column().classes("wb-page w-full"):
        wb_top_bar(
            i18n.tr("vram.title_bar"),
            action_label=i18n.tr("vram.new"),
            on_action=reset,
            action_icon="restart_alt",
        )
        with ui.row().classes("wb-body"):
            with ui.column().classes("wb-sidebar gap-2") as side:
                _render_models()
            with ui.column().classes("wb-main"):
                dot, status, status_meta = wb_status_strip(
                    _DOT_IDLE, i18n.tr("vram.estimate_label"), ""
                )
                with ui.column().classes("wb-workspace gap-4"):
                    with ui.column().classes("wb-panel w-full gap-3"):
                        dtype_chip = wb_panel_head(
                            i18n.tr("vram.params").upper(), chip="BF16"
                        )
                        with ui.row().classes("gap-2 w-full"):
                            mode = ui.select(
                                options=_MODES,
                                value="inference",
                                label=i18n.tr("vram.mode"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                            gpu = ui.select(
                                options=list(GPU_SPECS.keys()),
                                value="A100 80G",
                                label=i18n.tr("vram.gpu"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                            dtype = ui.select(
                                options=list(DTYPE_BYTES.keys()),
                                value="BF16",
                                label=i18n.tr("vram.dtype"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                        with ui.row().classes("gap-2"):
                            batch = ui.number(
                                label=i18n.tr("vram.batch"),
                                value=1,
                                min=1,
                                step=1,
                            ).props("dense outlined").classes("flex-1")
                            seq = ui.number(
                                label=i18n.tr("vram.seq_len"),
                                value=2048,
                                min=1,
                                step=512,
                            ).props("dense outlined").classes("flex-1")

                        train_box = ui.column().classes("gap-2")
                        with train_box:
                            lora = ui.switch(i18n.tr("vram.lora"), value=True)
                            lora_rank = ui.number(
                                label=i18n.tr("vram.lora_rank"),
                                value=8,
                                min=1,
                                step=8,
                            ).props("dense outlined").classes("w-28")
                            optimizer = ui.select(
                                options=list(OPTIMIZER_BYTES.keys()),
                                value="AdamW (32-bit)",
                                label=i18n.tr("vram.optimizer"),
                                with_input=False,
                            ).props("dense outlined").classes("w-48")
                            grad_ckpt = ui.switch(
                                i18n.tr("vram.grad_ckpt"), value=True
                            )
                            ddp = ui.switch(i18n.tr("vram.ddp"), value=False)
                            mixed = ui.switch(
                                i18n.tr("vram.mixed_precision"), value=True
                            )

                        serve_box = ui.column().classes("gap-2")
                        with serve_box:
                            with ui.row().classes("gap-2"):
                                num_gpus = ui.number(
                                    label=i18n.tr("vram.num_gpus"),
                                    value=1,
                                    min=1,
                                    step=1,
                                ).props("dense outlined").classes("w-28")
                                max_len = ui.number(
                                    label=i18n.tr("vram.max_model_len"),
                                    value=4096,
                                    min=1,
                                    step=512,
                                ).props("dense outlined").classes("w-40")
                                max_seqs = ui.number(
                                    label=i18n.tr("vram.max_num_seqs"),
                                    value=16,
                                    min=1,
                                    step=1,
                                ).props("dense outlined").classes("w-40")
                            with ui.row().classes("gap-2 items-end"):
                                with ui.column().classes("flex-1 gap-1"):
                                    ui.label(i18n.tr("vram.gpu_mem_util")).classes(
                                        "wb-inputbox-hint"
                                    )
                                    mem_util = ui.slider(
                                        min=0.5,
                                        max=0.95,
                                        step=0.05,
                                        value=0.9,
                                    ).classes("w-full")
                                kv_dtype = ui.select(
                                    options=["auto", "fp8"],
                                    value="auto",
                                    label=i18n.tr("vram.kv_dtype"),
                                    with_input=False,
                                ).props("dense outlined").classes("w-28")
                            cuda_graphs = ui.switch(
                                i18n.tr("vram.cuda_graphs"), value=True
                            )

                        manual_box = ui.column().classes("gap-2")
                        with manual_box:
                            ui.label(i18n.tr("vram.custom")).classes("wb-note")
                            with ui.row().classes("gap-2"):
                                m_params = ui.number(
                                    label=i18n.tr("vram.params_b"),
                                    value=0,
                                    step=0.1,
                                ).props("dense outlined").classes("flex-1")
                                m_hidden = ui.number(
                                    label=i18n.tr("vram.hidden"),
                                    value=0,
                                    step=64,
                                ).props("dense outlined").classes("flex-1")
                            with ui.row().classes("gap-2"):
                                m_layers = ui.number(
                                    label=i18n.tr("vram.layers"),
                                    value=0,
                                    step=1,
                                ).props("dense outlined").classes("flex-1")
                                m_heads = ui.number(
                                    label=i18n.tr("vram.heads"),
                                    value=0,
                                    step=1,
                                ).props("dense outlined").classes("flex-1")
                            with ui.row().classes("gap-2"):
                                m_kv_heads = ui.number(
                                    label=i18n.tr("vram.kv_heads"),
                                    value=0,
                                    step=1,
                                ).props("dense outlined").classes("flex-1")
                                m_vocab = ui.number(
                                    label=i18n.tr("vram.vocab"),
                                    value=0,
                                    step=1000,
                                ).props("dense outlined").classes("flex-1")
                            m_inter = ui.number(
                                label=i18n.tr("vram.intermediate"),
                                value=0,
                                step=64,
                            ).props("dense outlined").classes("w-full")
                        manual_box.set_visibility(False)

                    with ui.column().classes("wb-panel w-full gap-3"):
                        est_chip = wb_panel_head(
                            i18n.tr("vram.estimate_label").upper(), chip="·"
                        )
                        if est_chip is not None:
                            est_chip.visible = False
                        result_area

        with wb_input_bar():
            with ui.row().classes("items-center gap-2.5 w-full no-wrap"):
                with ui.row().classes(
                    "wb-inputbox items-center gap-2.5 no-wrap flex-1"
                ):
                    ui.label(i18n.tr("vram.model")).classes("wb-inputbox-prefix")
                    model_hint = ui.label(_model_hint()).classes(
                        "wb-inputbox-hint flex-1"
                    )
                wb_ghost_btn(
                    i18n.tr("vram.fetch_hf"),
                    on_click=lambda: fetch_hf(),
                    icon="cloud_download",
                )
                wb_primary_btn(
                    i18n.tr("vram.estimate_label"),
                    on_click=lambda: estimate(),
                    icon="calculate",
                )

    def _on_mode_change(_e) -> None:
        """Sync input groups and pool meta when the mode changes."""
        _sync_boxes()
        _refresh_meta()

    def _on_dtype_change(_e) -> None:
        """Mirror the selected precision into the panel chip."""
        if dtype_chip is not None:
            dtype_chip.text = dtype.value

    mode.on_value_change(_on_mode_change)
    gpu.on_value_change(lambda _: _refresh_meta())
    dtype.on_value_change(_on_dtype_change)
    num_gpus.on_value_change(lambda _: _refresh_meta())
    _sync_boxes()
    _refresh_meta()

    def _collect_request() -> VramRequest:
        """Assemble a VramRequest from the form widgets."""
        return VramRequest(
            model_id="" if model_state["value"] == "custom" else model_state["value"],
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
        """Draw the estimate into the result panel."""
        result_area.clear()
        n = _gpu_count()
        with result_area:
            with ui.row().classes("items-end gap-3 no-wrap"):
                ui.label(f"{est.total_gb:.2f} GiB").classes("wb-big-value")
                ui.label(
                    i18n.tr(
                        "vram.fits_on" if est.fits else "vram.over_by",
                        n=n,
                        gpu=gpu.value,
                        gb=abs(est.headroom_gb),
                    )
                ).classes("wb-fits-note" + ("" if est.fits else " over"))
            wb_stack_bar(
                [
                    (
                        it.gb / est.total_gb * 100 if est.total_gb else 0.0,
                        _ITEM_COLORS.get(it.key, _DOT_IDLE),
                    )
                    for it in est.items
                ]
            )
            wb_legend(
                [
                    (_ITEM_COLORS.get(it.key, _DOT_IDLE), i18n.tr(_ITEM_LEGEND[it.key]))
                    for it in est.items
                    if it.key in _ITEM_LEGEND
                ]
            )
            for it in est.items:
                wb_detail_row(i18n.tr(it.key), f"{it.gb:.2f} GiB")
            wb_detail_row(
                i18n.tr("vram.total_row"), f"{est.total_gb:.2f} GiB", total=True
            )
            wb_detail_row(
                i18n.tr("vram.utilization"), f"{est.utilization_pct:.0f}%"
            )
            wb_detail_row(i18n.tr("vram.headroom"), f"{est.headroom_gb:.2f} GiB")
            if est.vllm_command:
                wb_detail_row(i18n.tr("vram.max_seqs"), str(est.max_seqs))
                wb_detail_row(
                    i18n.tr("vram.kv_per_token"), f"{est.kv_per_token_kb:.1f} KB"
                )
                wb_detail_row(
                    i18n.tr("vram.kv_per_seq"), f"{est.kv_per_seq_gb:.2f} GiB"
                )
                wb_detail_row(
                    i18n.tr("vram.prompt_tps"), f"{est.prompt_tps:,.0f} tok/s"
                )
                wb_detail_row(i18n.tr("vram.gen_tps"), f"{est.gen_tps:,.0f} tok/s")
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.code(est.vllm_command).classes("wb-code flex-1")
                    wb_ghost_btn(
                        i18n.tr("common.copy"),
                        on_click=lambda: (
                            ui.run_javascript(
                                f"navigator.clipboard.writeText({est.vllm_command!r})"
                            ),
                            ui.notify(i18n.tr("common.copied")),
                        ),
                        icon="content_copy",
                    )
            for note in est.notes:
                ui.label(f"• {note}").classes("wb-note")
        if est_chip is not None:
            est_chip.visible = True
            est_chip.text = i18n.tr("vram.fits" if est.fits else "vram.not_fits")
            est_chip.style(f"color:{_DOT_FIT if est.fits else _DOT_OVER}")
        dot.style(f"background:{_DOT_FIT if est.fits else _DOT_OVER}")
        status.text = i18n.tr(
            "vram.fits_on" if est.fits else "vram.over_by",
            n=n,
            gpu=gpu.value,
            gb=abs(est.headroom_gb),
        )
        _refresh_meta()

    def estimate() -> None:
        """Run the (synchronous) estimation and render the result."""
        try:
            render_result(service.estimate(_collect_request()))
        except ValueError as exc:
            dot.style(f"background:{_DOT_ERROR}")
            status.text = str(exc)
            ui.notify(str(exc), type="warning")

    async def fetch_hf() -> None:
        """Fetch a HuggingFace config and fill the manual model fields."""
        model_id = model_state["value"]
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

