"""VRAM tab: mode/model/GPU/precision inputs, breakdown, vLLM command.

Mirrors ``nicegui/pages/vram_page.py``: estimation is pure CPU math and
runs synchronously in the click handler; only the optional HuggingFace
config fetch for custom models runs in an app worker.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    ProgressBar,
    Select,
    Static,
)

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

_MODES: tuple[str, ...] = ("inference", "training", "serving")
_HF_WORKER_GROUP = "hf_fetch"
#: (input id, label i18n key) of the manual model-params fields.
_MANUAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("m_params", "vram.params_b"),
    ("m_hidden", "vram.hidden"),
    ("m_layers", "vram.layers"),
    ("m_heads", "vram.heads"),
    ("m_kv_heads", "vram.kv_heads"),
    ("m_vocab", "vram.vocab"),
    ("m_inter", "vram.intermediate"),
)
#: Manual fields required before a custom model can be fetched/estimated.
_MANUAL_REQUIRED: tuple[str, ...] = ("m_params", "m_hidden", "m_layers")


class VramPage(VerticalScroll):
    """LLM VRAM estimation form with breakdown and vLLM command output."""

    DEFAULT_CSS = """
    VramPage {
        height: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, ctx: AppContext) -> None:
        """Initialize with the shared application context.

        Args:
            ctx: Application context (provides the vram service).
        """
        super().__init__()
        self.ctx = ctx

    def compose(self) -> ComposeResult:
        """Build the input form and the result area."""
        yield Static(i18n.tr("vram.title"))
        yield Static(i18n.tr("vram.mode"))
        yield Select(_mode_options(), id="mode", value="inference")
        yield Static(i18n.tr("vram.preset"))
        yield Select(_preset_options(), id="preset", value="Qwen2.5-7B")
        with Vertical(id="manual_box"):
            yield Static(i18n.tr("vram.custom"))
            for field_id, key in _MANUAL_FIELDS:
                yield Static(i18n.tr(key))
                yield Input(id=field_id)
        yield Static(i18n.tr("vram.gpu"))
        yield Select(_name_options(GPU_SPECS), id="gpu", value="A100 80G")
        yield Static(i18n.tr("vram.dtype"))
        yield Select(_name_options(DTYPE_BYTES), id="dtype", value="BF16")
        yield Static(i18n.tr("vram.batch"))
        yield Input(id="batch", value="1")
        yield Static(i18n.tr("vram.seq_len"))
        yield Input(id="seq", value="2048")
        with Vertical(id="train_box"):
            yield Checkbox(i18n.tr("vram.lora"), value=True, id="lora")
            yield Static(i18n.tr("vram.lora_rank"))
            yield Input(id="lora_rank", value="8")
            yield Static(i18n.tr("vram.optimizer"))
            yield Select(
                _name_options(OPTIMIZER_BYTES), id="optimizer", value="AdamW (32-bit)"
            )
            yield Checkbox(i18n.tr("vram.grad_ckpt"), value=True, id="grad_ckpt")
            yield Checkbox(i18n.tr("vram.ddp"), value=False, id="ddp")
            yield Checkbox(i18n.tr("vram.mixed_precision"), value=True, id="mixed")
        with Vertical(id="serve_box"):
            yield Static(i18n.tr("vram.num_gpus"))
            yield Input(id="num_gpus", value="1")
            yield Static(i18n.tr("vram.max_model_len"))
            yield Input(id="max_len", value="4096")
            yield Static(i18n.tr("vram.max_num_seqs"))
            yield Input(id="max_seqs", value="16")
            yield Static(i18n.tr("vram.gpu_mem_util"))
            yield Input(id="mem_util", value="0.9")
            yield Static(i18n.tr("vram.kv_dtype"))
            yield Select([("auto", "auto"), ("fp8", "fp8")], id="kv_dtype", value="auto")
            yield Checkbox(i18n.tr("vram.cuda_graphs"), value=True, id="cuda_graphs")
        with Horizontal():
            yield Button(i18n.tr("vram.estimate"), id="btn_estimate", variant="primary")
            yield Button(i18n.tr("vram.fetch_hf"), id="btn_fetch")
        yield Static("", id="vram_total")
        yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="vram_bar")
        yield Static("", id="vram_meta")
        yield DataTable(id="breakdown")
        yield Static("", id="vllm_cmd")
        yield Static("", id="vram_notes")

    def on_mount(self) -> None:
        """Hide conditional boxes and the (initially empty) result area."""
        for box_id in ("manual_box", "train_box", "serve_box", "vllm_cmd", "vram_notes"):
            self.query_one(f"#{box_id}").styles.display = "none"
        table = self.query_one("#breakdown", DataTable)
        table.add_columns((i18n.tr("common.details"), "item"), ("GiB", "gib"))
        table.styles.display = "none"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route estimate / fetch-HF clicks."""
        if event.button.id == "btn_estimate":
            self._estimate()
        elif event.button.id == "btn_fetch":
            self._fetch_hf()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Show/hide the mode- and preset-dependent boxes."""
        if event.select.id in ("mode", "preset"):
            self._sync_boxes()

    def _sync_boxes(self) -> None:
        """Toggle the manual/training/serving boxes per mode and preset."""
        mode = self.query_one("#mode", Select).value
        preset = self.query_one("#preset", Select).value
        self._show("#manual_box", preset == "custom")
        self._show("#train_box", mode == "training")
        self._show("#serve_box", mode == "serving")

    def _show(self, widget_id: str, show: bool) -> None:
        """Show or hide the widget with the given id."""
        self.query_one(widget_id).styles.display = "block" if show else "none"

    def _estimate(self) -> None:
        """Run the (synchronous) estimation and render the result."""
        try:
            est = self.ctx.vram.estimate(self._collect_request())
        except ValueError as exc:
            self.app.notify(str(exc), severity="warning")
            return
        self._render_result(est)

    def _collect_request(self) -> VramRequest:
        """Assemble a VramRequest from the form widgets."""
        preset = self.query_one("#preset", Select).value
        return VramRequest(
            model_id="" if preset == "custom" else preset,
            gpu=self.query_one("#gpu", Select).value,
            mode=self.query_one("#mode", Select).value,
            dtype=self.query_one("#dtype", Select).value,
            batch_size=self._int("#batch", 1),
            seq_length=self._int("#seq", 1),
            manual_params_b=self._float("#m_params", 0.0),
            manual_hidden=self._int("#m_hidden", 0),
            manual_layers=self._int("#m_layers", 0),
            manual_heads=self._int("#m_heads", 0),
            manual_kv_heads=self._int("#m_kv_heads", 0),
            manual_vocab=self._int("#m_vocab", 0),
            manual_intermediate=self._int("#m_inter", 0),
            lora=self.query_one("#lora", Checkbox).value,
            lora_rank=self._int("#lora_rank", 8),
            optimizer=self.query_one("#optimizer", Select).value,
            gradient_checkpointing=self.query_one("#grad_ckpt", Checkbox).value,
            ddp=self.query_one("#ddp", Checkbox).value,
            mixed_precision=self.query_one("#mixed", Checkbox).value,
            num_gpus=self._int("#num_gpus", 1),
            max_model_len=self._int("#max_len", 4096),
            max_num_seqs=self._int("#max_seqs", 16),
            gpu_memory_utilization=self._float("#mem_util", 0.9),
            kv_cache_dtype=self.query_one("#kv_dtype", Select).value,
            cuda_graphs=self.query_one("#cuda_graphs", Checkbox).value,
        )

    def _int(self, widget_id: str, default: int) -> int:
        """Parse an integer input (falls back to *default* when invalid)."""
        raw = self.query_one(widget_id, Input).value.strip()
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    def _float(self, widget_id: str, default: float) -> float:
        """Parse a float input (falls back to *default* when invalid)."""
        raw = self.query_one(widget_id, Input).value.strip()
        try:
            return float(raw) if raw else default
        except ValueError:
            return default

    def _fetch_hf(self) -> None:
        """Validate and launch the HuggingFace config fetch worker."""
        preset = self.query_one("#preset", Select).value
        if preset == "custom" and not any(
            self.query_one(f"#{field_id}", Input).value.strip()
            for field_id in _MANUAL_REQUIRED
        ):
            self.app.notify(i18n.tr("vram.need_manual"), severity="warning")
            return
        self.run_worker(
            self._fetch_hf_worker(preset),
            name="hf_fetch",
            group=_HF_WORKER_GROUP,
            exclusive=True,
        )

    async def _fetch_hf_worker(self, model_id: str) -> None:
        """Fetch the HF config and fill the manual model fields."""
        self.app.notify("Fetching config\u2026")
        config = await self.ctx.vram.fetch_model_config(model_id)
        if config is None:
            self.app.notify(i18n.tr("vram.fetch_failed"), severity="error")
            return
        params = VramService.estimate_params(config)
        if params:
            self.query_one("#m_params", Input).value = f"{params:g}"
        self.query_one("#m_hidden", Input).value = str(config.get("hidden_size", 0) or 0)
        self.query_one("#m_layers", Input).value = str(
            config.get("num_hidden_layers", 0) or 0
        )
        self.query_one("#m_heads", Input).value = str(
            config.get("num_attention_heads", 0) or 0
        )
        self.query_one("#m_kv_heads", Input).value = str(
            config.get("num_key_value_heads", 0) or 0
        )
        self.query_one("#m_vocab", Input).value = str(config.get("vocab_size", 0) or 0)
        self.query_one("#m_inter", Input).value = str(
            config.get("intermediate_size", 0) or 0
        )
        self.app.notify(i18n.tr("common.saved"), severity="success")

    def _render_result(self, est: VramEstimate) -> None:
        """Draw the estimate into the result area."""
        fit_key = "vram.fits" if est.fits else "vram.not_fits"
        self.query_one("#vram_total", Static).update(
            f"{i18n.tr('vram.total')}: {est.total_gb:.2f} GiB \u2014 {i18n.tr(fit_key)}"
        )
        self.query_one("#vram_bar", ProgressBar).update(
            total=100, progress=est.utilization_pct
        )
        self.query_one("#vram_meta", Static).update(
            f"{i18n.tr('vram.utilization')}: {est.utilization_pct:.1f}%  "
            f"{i18n.tr('vram.headroom')}: {est.headroom_gb:.2f} GiB "
            f"({self.query_one('#gpu', Select).value}, {est.gpu_vram_gb:.0f} GiB)"
        )
        self._render_breakdown(est)
        self._render_vllm(est)
        self._render_notes(est)

    def _render_breakdown(self, est: VramEstimate) -> None:
        """Fill the breakdown table with the estimate items."""
        table = self.query_one("#breakdown", DataTable)
        table.clear()  # columns are declared once in on_mount
        table.add_rows([(i18n.tr(item.key), f"{item.gb:.2f}") for item in est.items])
        table.styles.display = "block"

    def _render_vllm(self, est: VramEstimate) -> None:
        """Render the serving extras and vLLM command (serving only)."""
        cmd = self.query_one("#vllm_cmd", Static)
        if not est.vllm_command:
            cmd.update("")
            cmd.styles.display = "none"
            return
        cmd.update(
            f"{i18n.tr('vram.vllm_cmd')}\n"
            f"{i18n.tr('vram.max_seqs')}: {est.max_seqs}   "
            f"{i18n.tr('vram.kv_per_token')}: {est.kv_per_token_kb:.1f} KB   "
            f"{i18n.tr('vram.kv_per_seq')}: {est.kv_per_seq_gb:.2f} GiB\n"
            f"{i18n.tr('vram.prompt_tps')}: {est.prompt_tps:,.0f} tok/s   "
            f"{i18n.tr('vram.gen_tps')}: {est.gen_tps:,.0f} tok/s\n"
            f"{est.vllm_command}"
        )
        cmd.styles.display = "block"

    def _render_notes(self, est: VramEstimate) -> None:
        """Render the estimate warning notes (if any)."""
        notes = self.query_one("#vram_notes", Static)
        if not est.notes:
            notes.update("")
            notes.styles.display = "none"
            return
        notes.update(
            i18n.tr("vram.notes") + "\n" + "\n".join(f"\u2022 {n}" for n in est.notes)
        )
        notes.styles.display = "block"


def _mode_options() -> list[tuple[str, str]]:
    """(i18n label, mode) options for the mode select."""
    return [(i18n.tr(f"vram.mode.{mode}"), mode) for mode in _MODES]


def _preset_options() -> list[tuple[str, str]]:
    """(label, preset name) options; 'custom' first, like NiceGUI."""
    return [(i18n.tr("vram.custom"), "custom"), *[(n, n) for n in MODEL_PRESETS]]


def _name_options(mapping: dict[str, object]) -> list[tuple[str, str]]:
    """(name, name) options for a dict-keyed select."""
    return [(name, name) for name in mapping]
