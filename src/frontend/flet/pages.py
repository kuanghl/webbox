"""Flet tab pages: Translate / VRAM / Settings.

Each ``build_*_tab`` returns a Flet control tree wired to the shared
``core`` / ``modules`` services (AGENTS.md 3.4). Web-mode file handling:
uploads arrive as bytes via ``FilePicker(with_data=True)`` and are written
to a temp file for the babeldoc pipeline; downloads go through
``file_picker.save_file(src_bytes=...)``.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import flet as ft

from ...core import i18n
from ...core.constants import (
    DEFAULT_LANG_IN,
    DEFAULT_LANG_OUT,
    THEMES,
    TRANSLATE_LANGUAGES,
    UI_LANGUAGES,
    USERS,
)
from ...core.context import AppContext
from ...core.store import PROVIDER_DEFAULTS, SettingsStore
from ...modules.translate.interfaces import TranslateJob, TranslateOutcome
from ...modules.vram.models import (
    DTYPE_BYTES,
    GPU_SPECS,
    MODEL_PRESETS,
    OPTIMIZER_BYTES,
    VramEstimate,
    VramRequest,
)
from ...modules.vram.service import VramService

logger = logging.getLogger(__name__)

_VRAM_MODES = ("inference", "training", "serving")


def _opts(mapping: dict[str, str]) -> list[ft.dropdown.Option]:
    """Build dropdown options from a ``{key: label}`` mapping."""
    return [ft.dropdown.Option(key=k, text=v) for k, v in mapping.items()]


def _str_opts(values: list[str]) -> list[ft.dropdown.Option]:
    """Build dropdown options from plain string values (key = text)."""
    return [ft.dropdown.Option(key=v, text=v) for v in values]


def _num(value: str | None, default: float = 0.0) -> float:
    """Parse a float from a text field, falling back to ``default``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: str | None, default: int = 0) -> int:
    """Parse an int from a text field, falling back to ``default``."""
    return int(_num(value, default))


def _notify(page: ft.Page, text: str) -> None:
    """Show a transient snackbar message."""
    page.show_dialog(ft.SnackBar(content=ft.Text(text)))


def _card(title: str, *controls: ft.Control) -> ft.Container:
    """Section card with a bold title and padded body."""
    return ft.Container(
        ft.Column([ft.Text(title, size=16, weight=ft.FontWeight.BOLD), *controls], spacing=10),
        padding=16,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.GREY),
        border_radius=10,
    )


def build_translate_tab(page: ft.Page, ctx: AppContext) -> ft.Control:
    """Translate tab: PDF upload, provider/model config, job controls.

    Args:
        page: Flet page.
        ctx: Application context.

    Returns:
        The tab's control tree.
    """
    settings = ctx.settings.load()
    state: dict = {"file": None, "task": None}

    file_label = ft.Text(i18n.tr("tr.upload_hint"), size=12, color=ft.Colors.GREY)
    lang_in = ft.Dropdown(
        options=_opts(TRANSLATE_LANGUAGES),
        value=DEFAULT_LANG_IN,
        label=i18n.tr("tr.source_lang"),
        width=180,
    )
    lang_out = ft.Dropdown(
        options=_opts(TRANSLATE_LANGUAGES),
        value=DEFAULT_LANG_OUT,
        label=i18n.tr("tr.target_lang"),
        width=180,
    )
    provider = ft.Dropdown(
        options=_str_opts(list(PROVIDER_DEFAULTS)),
        value=settings.provider,
        width=180,
    )
    model_field = ft.TextField(value=settings.model, label=i18n.tr("tr.model"), width=260)
    base_field = ft.TextField(
        value=settings.base_url or "",
        label=i18n.tr("tr.base_url"),
        width=260,
    )
    api_field = ft.TextField(
        value=settings.api_key or "",
        label=i18n.tr("tr.api_key"),
        password=True,
        can_reveal_password=True,
        width=260,
    )
    pages_field = ft.TextField(value="", label=i18n.tr("tr.pages"), width=260)
    dual_chk = ft.Checkbox(value=True, label=i18n.tr("tr.dual"))
    mono_chk = ft.Checkbox(value=False, label=i18n.tr("tr.mono"))
    qps_field = ft.TextField(value="5", label=i18n.tr("tr.qps"), width=120)
    out_field = ft.TextField(value="", label=i18n.tr("tr.output_dir"), width=260)
    start_btn = ft.Button(i18n.tr("common.start"), icon=ft.Icons.TRANSLATE)
    cancel_btn = ft.TextButton(i18n.tr("common.cancel"), visible=False)
    progress = ft.ProgressBar(value=0, visible=False, width=400)
    status = ft.Text("", size=13)
    result_box = ft.Column(spacing=8, visible=False)

    file_picker = ft.FilePicker()
    page.overlay.append(file_picker)

    async def _pick(e: ft.ControlEvent) -> None:
        """Open the file dialog and store the picked PDF for the pipeline."""
        files = await file_picker.pick_files(
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[".pdf"],
            allow_multiple=False,
            with_data=True,
        )
        if not files or files[0].bytes is None:
            return
        picked = files[0]
        fd, path = tempfile.mkstemp(suffix=".pdf", prefix="webbox_upload_")
        with open(fd, "wb") as f:
            f.write(picked.bytes)
        state["file"] = path
        file_label.value = f"{picked.name} ({picked.size // 1024} KB)"
        page.update()

    def _on_provider_changed(e: ft.ControlEvent) -> None:
        """Pre-fill model and base URL when the provider changes."""
        model, url = SettingsStore.provider_defaults(e.control.value)
        if model:
            model_field.value = model
        if url:
            base_field.value = url
        page.update()

    provider.on_select = _on_provider_changed

    def _download_handler(path: str):
        """Build an async click handler that downloads one finished PDF."""

        async def handler(e: ft.ControlEvent) -> None:
            p = Path(path)
            if p.is_file():
                await file_picker.save_file(file_name=p.name, src_bytes=p.read_bytes())

        return handler

    def _collect_job() -> TranslateJob | None:
        """Build a job from the form, or None when inputs are invalid."""
        if state["file"] is None:
            _notify(page, i18n.tr("tr.no_file"))
            return None
        if not api_field.value and provider.value != "Ollama":
            _notify(page, i18n.tr("tr.no_api_key"))
            return None
        return TranslateJob(
            pdf_path=state["file"],
            lang_in=lang_in.value,
            lang_out=lang_out.value,
            provider=provider.value,
            model=model_field.value or "",
            api_key=api_field.value or "",
            base_url=base_field.value or "",
            pages=pages_field.value or "",
            dual=bool(dual_chk.value),
            mono=bool(mono_chk.value),
            qps=_num(qps_field.value, 1.0),
            output_dir=out_field.value or "",
        )

    async def _worker(job: TranslateJob) -> None:
        """Consume the translation generator, updating the widgets directly."""
        try:
            async for event in ctx.translate.run(job):
                if isinstance(event, TranslateOutcome):
                    if event.ok:
                        status.value = f"{i18n.tr('status.finished')} ({event.elapsed_s:.0f}s)"
                        progress.value = 1.0
                        result_box.visible = True
                        result_box.controls.clear()
                        for p in event.output_paths:
                            result_box.controls.append(
                                ft.Row(
                                    [
                                        ft.Text(f"{i18n.tr('tr.result_file')}: {p}", size=13),
                                        ft.Button(
                                            i18n.tr("tr.download"),
                                            icon=ft.Icons.DOWNLOAD,
                                            on_click=_download_handler(p),
                                        ),
                                    ],
                                    spacing=8,
                                )
                            )
                    else:
                        status.value = i18n.tr("status.error")
                        result_box.visible = True
                        result_box.controls.clear()
                        result_box.controls.append(
                            ft.Text(event.error, size=13, color=ft.Colors.RED_300)
                        )
                else:
                    detail = event.message
                    if event.total_pages:
                        detail = f"{event.page}/{event.total_pages} {detail}"
                    status.value = (
                        f"{i18n.tr('status.running')} — {i18n.tr('tr.stage')}: "
                        f"{detail} ({event.overall_pct}%)"
                    )
                    progress.value = event.overall_pct / 100
        except asyncio.CancelledError:
            status.value = i18n.tr("status.cancelled")
            raise
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            logger.exception("Flet translate job failed")
            status.value = str(exc)
            _notify(page, str(exc))
        finally:
            start_btn.disabled = False
            cancel_btn.visible = False
            state["task"] = None
            page.update()

    def start(e: ft.ControlEvent) -> None:
        """Validate inputs and launch the background translation task."""
        if state["task"] is not None:
            return
        job = _collect_job()
        if job is None:
            return
        result_box.controls.clear()
        result_box.visible = False
        progress.visible = True
        progress.value = 0
        status.value = f"{i18n.tr('status.running')} — {i18n.tr('tr.stage')}:"
        start_btn.disabled = True
        cancel_btn.visible = True
        page.update()
        state["task"] = asyncio.create_task(_worker(job))

    def cancel(e: ft.ControlEvent) -> None:
        """Cancel the in-flight translation task."""
        task = state["task"]
        if task is not None:
            task.cancel()

    start_btn.on_click = start
    cancel_btn.on_click = cancel

    return ft.Column(
        [
            _card(
                i18n.tr("common.file"),
                ft.Row(
                    [
                        ft.Button(
                            i18n.tr("tr.upload"),
                            icon=ft.Icons.UPLOAD_FILE,
                            on_click=_pick,
                        ),
                        file_label,
                    ],
                    spacing=12,
                ),
            ),
            _card(i18n.tr("tr.title"), ft.Row([lang_in, lang_out], spacing=12)),
            _card(
                i18n.tr("tr.provider"),
                ft.Row([provider, model_field], spacing=12, wrap=True),
                ft.Row([base_field, api_field], spacing=12, wrap=True),
                ft.Row([pages_field, qps_field, out_field], spacing=12, wrap=True),
                ft.Row([dual_chk, mono_chk], spacing=12),
            ),
            _card(
                i18n.tr("common.status"),
                ft.Row([start_btn, cancel_btn], spacing=12),
                progress,
                status,
                result_box,
            ),
        ],
        spacing=12,
    )


def build_vram_tab(page: ft.Page, ctx: AppContext) -> ft.Control:
    """VRAM tab: mode/model/GPU/precision inputs, breakdown, vLLM command.

    Estimation is pure CPU math, so it runs synchronously in the click
    handler; only the optional HuggingFace fetch is async.

    Args:
        page: Flet page.
        ctx: Application context (provides the vram service).

    Returns:
        The tab's control tree.
    """
    service: VramService = ctx.vram
    result_box = ft.Column(spacing=8)

    mode = ft.Dropdown(options=_str_opts(list(_VRAM_MODES)), value="inference", width=140)
    preset = ft.Dropdown(
        options=_str_opts(["custom", *MODEL_PRESETS.keys()]), value="Qwen2.5-7B", width=220
    )
    m_params = ft.TextField(value="0", label=i18n.tr("vram.params_b"), width=140)
    m_hidden = ft.TextField(value="0", label=i18n.tr("vram.hidden"), width=140)
    m_layers = ft.TextField(value="0", label=i18n.tr("vram.layers"), width=140)
    m_heads = ft.TextField(value="0", label=i18n.tr("vram.heads"), width=140)
    m_kv_heads = ft.TextField(value="0", label=i18n.tr("vram.kv_heads"), width=140)
    m_vocab = ft.TextField(value="0", label=i18n.tr("vram.vocab"), width=140)
    m_inter = ft.TextField(value="0", label=i18n.tr("vram.intermediate"), width=140)
    manual_box = ft.Column(
        [
            ft.Text(i18n.tr("vram.custom"), size=13, weight=ft.FontWeight.BOLD),
            ft.Row([m_params, m_hidden, m_layers, m_heads], spacing=8, wrap=True),
            ft.Row([m_kv_heads, m_vocab, m_inter], spacing=8, wrap=True),
        ],
        spacing=8,
        visible=False,
    )
    gpu = ft.Dropdown(options=_str_opts(list(GPU_SPECS.keys())), value="A100 80G", width=180)
    dtype = ft.Dropdown(options=_str_opts(list(DTYPE_BYTES.keys())), value="BF16", width=120)
    batch = ft.TextField(value="1", label=i18n.tr("vram.batch"), width=120)
    seq = ft.TextField(value="2048", label=i18n.tr("vram.seq_len"), width=120)

    lora = ft.Switch(label=i18n.tr("vram.lora"), value=True)
    lora_rank = ft.TextField(value="8", label=i18n.tr("vram.lora_rank"), width=120)
    optimizer = ft.Dropdown(
        options=_str_opts(list(OPTIMIZER_BYTES.keys())), value="AdamW (32-bit)", width=180
    )
    grad_ckpt = ft.Switch(label=i18n.tr("vram.grad_ckpt"), value=True)
    ddp = ft.Switch(label=i18n.tr("vram.ddp"), value=False)
    mixed = ft.Switch(label=i18n.tr("vram.mixed_precision"), value=True)
    train_box = ft.Column(
        [
            ft.Row([lora, lora_rank, optimizer], spacing=12, wrap=True),
            ft.Row([grad_ckpt, ddp, mixed], spacing=12, wrap=True),
        ],
        spacing=8,
        visible=False,
    )

    num_gpus = ft.TextField(value="1", label=i18n.tr("vram.num_gpus"), width=120)
    max_len = ft.TextField(value="4096", label=i18n.tr("vram.max_model_len"), width=140)
    max_seqs = ft.TextField(value="16", label=i18n.tr("vram.max_num_seqs"), width=140)
    mem_util = ft.Slider(min=0.5, max=0.95, divisions=9, label="{value:.2f}")
    kv_dtype = ft.Dropdown(options=_str_opts(["auto", "fp8"]), value="auto", width=100)
    cuda_graphs = ft.Switch(label=i18n.tr("vram.cuda_graphs"), value=True)
    serve_box = ft.Column(
        [
            ft.Row([num_gpus, max_len, max_seqs], spacing=12, wrap=True),
            ft.Row([mem_util, kv_dtype, cuda_graphs], spacing=12, wrap=True),
        ],
        spacing=8,
        visible=False,
    )

    def _sync_boxes() -> None:
        """Show only the input groups relevant to the selected mode/preset."""
        manual_box.visible = preset.value == "custom"
        train_box.visible = mode.value == "training"
        serve_box.visible = mode.value == "serving"
        page.update()

    mode.on_select = lambda e: _sync_boxes()
    preset.on_select = lambda e: _sync_boxes()

    def _collect_request() -> VramRequest:
        """Assemble a VramRequest from the form widgets."""
        return VramRequest(
            model_id="" if preset.value == "custom" else preset.value,
            gpu=gpu.value,
            mode=mode.value,
            dtype=dtype.value,
            batch_size=_int(batch.value, 1),
            seq_length=_int(seq.value, 1),
            manual_params_b=_num(m_params.value),
            manual_hidden=_int(m_hidden.value),
            manual_layers=_int(m_layers.value),
            manual_heads=_int(m_heads.value),
            manual_kv_heads=_int(m_kv_heads.value),
            manual_vocab=_int(m_vocab.value),
            manual_intermediate=_int(m_inter.value),
            lora=bool(lora.value),
            lora_rank=_int(lora_rank.value, 8),
            optimizer=optimizer.value,
            gradient_checkpointing=bool(grad_ckpt.value),
            ddp=bool(ddp.value),
            mixed_precision=bool(mixed.value),
            num_gpus=_int(num_gpus.value, 1),
            max_model_len=_int(max_len.value, 4096),
            max_num_seqs=_int(max_seqs.value, 16),
            gpu_memory_utilization=float(mem_util.value or 0.9),
            kv_cache_dtype=kv_dtype.value,
            cuda_graphs=bool(cuda_graphs.value),
        )

    def render_result(est: VramEstimate) -> None:
        """Draw the estimate into the result column."""
        result_box.controls.clear()
        result_box.controls.append(
            ft.Row(
                [
                    ft.Text(
                        f"{i18n.tr('vram.total')}: {est.total_gb} GiB",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        i18n.tr("vram.fits" if est.fits else "vram.not_fits"),
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREEN if est.fits else ft.Colors.RED,
                    ),
                ],
                spacing=12,
            )
        )
        result_box.controls.append(
            ft.ProgressBar(value=est.utilization_pct / 100, width=480)
        )
        result_box.controls.append(
            ft.Text(
                f"{i18n.tr('vram.utilization')}: {est.utilization_pct}%  "
                f"{i18n.tr('vram.headroom')}: {est.headroom_gb} GiB "
                f"({gpu.value}, {est.gpu_vram_gb} GiB)",
                size=12,
                color=ft.Colors.GREY,
            )
        )
        if est.items:
            rows = [
                ft.Row(
                    [
                        ft.Text(i18n.tr(it.key), size=13, col=8),
                        ft.Text(
                            f"{it.gb:.2f} GiB",
                            size=13,
                            col=4,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=8,
                )
                for it in est.items
            ]
            result_box.controls.append(ft.Column(rows, spacing=4))
        if est.vllm_command:
            result_box.controls.append(
                ft.Text(
                    f"{i18n.tr('vram.max_seqs')}: {est.max_seqs}   "
                    f"{i18n.tr('vram.kv_per_token')}: {est.kv_per_token_kb:.1f} KB   "
                    f"{i18n.tr('vram.kv_per_seq')}: {est.kv_per_seq_gb:.2f} GiB",
                    size=12,
                )
            )
            result_box.controls.append(
                ft.Text(
                    f"{i18n.tr('vram.prompt_tps')}: {est.prompt_tps:,.0f} tok/s   "
                    f"{i18n.tr('vram.gen_tps')}: {est.gen_tps:,.0f} tok/s",
                    size=12,
                    color=ft.Colors.GREY,
                )
            )
            result_box.controls.append(
                ft.Container(
                    ft.Text(est.vllm_command, size=12, selectable=True),
                    padding=10,
                    bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
                    border_radius=6,
                )
            )
        for note in est.notes:
            result_box.controls.append(ft.Text(f"• {note}", size=12, color=ft.Colors.ORANGE))
        page.update()

    def estimate(e: ft.ControlEvent) -> None:
        """Run the (synchronous) estimation and render the result."""
        try:
            render_result(service.estimate(_collect_request()))
        except ValueError as exc:
            _notify(page, str(exc))

    async def fetch_hf(e: ft.ControlEvent) -> None:
        """Fetch a HuggingFace config and fill the manual model fields."""
        model_id = preset.value
        if model_id == "custom" and not any(
            (_num(m_params.value), _int(m_hidden.value), _int(m_layers.value))
        ):
            _notify(page, i18n.tr("vram.need_manual"))
            return
        config = await service.fetch_model_config(model_id)
        if config is None:
            _notify(page, i18n.tr("vram.fetch_failed"))
            return
        params = VramService.estimate_params(config)
        if params:
            m_params.value = str(params)
        m_hidden.value = str(config.get("hidden_size", 0) or 0)
        m_layers.value = str(config.get("num_hidden_layers", 0) or 0)
        m_heads.value = str(config.get("num_attention_heads", 0) or 0)
        m_kv_heads.value = str(config.get("num_key_value_heads", 0) or 0)
        m_vocab.value = str(config.get("vocab_size", 0) or 0)
        m_inter.value = str(config.get("intermediate_size", 0) or 0)
        _notify(page, i18n.tr("common.saved"))
        page.update()

    return ft.Row(
        [
            _card(
                i18n.tr("vram.title"),
                ft.Row([mode, preset, gpu, dtype], spacing=12, wrap=True),
                manual_box,
                ft.Row([batch, seq], spacing=12),
                train_box,
                serve_box,
                ft.Row(
                    [
                        ft.Button(
                            i18n.tr("vram.estimate"),
                            icon=ft.Icons.CALCULATE,
                            on_click=estimate,
                        ),
                        ft.Button(
                            i18n.tr("vram.fetch_hf"),
                            icon=ft.Icons.CLOUD_DOWNLOAD,
                            on_click=fetch_hf,
                        ),
                    ],
                    spacing=12,
                ),
            ),
            ft.Column(
                [
                    ft.Text(i18n.tr("common.result"), size=16, weight=ft.FontWeight.BOLD),
                    result_box,
                ],
                spacing=8,
                expand=True,
            ),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def build_settings_tab(page: ft.Page, ctx: AppContext) -> ft.Control:
    """Settings tab: default provider/model, language, theme, user.

    Args:
        page: Flet page.
        ctx: Application context (settings store).

    Returns:
        The tab's control tree.
    """
    settings = ctx.settings.load()
    provider = ft.Dropdown(options=_str_opts(list(PROVIDER_DEFAULTS)), value=settings.provider, width=200)
    model_field = ft.TextField(value=settings.model, label=i18n.tr("st.model"), width=260)
    base_field = ft.TextField(value=settings.base_url or "", label=i18n.tr("st.base_url"), width=260)
    api_field = ft.TextField(
        value=settings.api_key or "",
        label=i18n.tr("st.api_key"),
        password=True,
        can_reveal_password=True,
        width=260,
    )
    language = ft.Dropdown(options=_opts(UI_LANGUAGES), value=settings.language, width=160)
    theme = ft.Dropdown(options=_opts(THEMES), value=settings.theme, width=120)
    user = ft.Dropdown(
        options=[ft.dropdown.Option(key=u, text=u) for u in USERS],
        value=settings.user,
        width=140,
    )

    def save(e: ft.ControlEvent) -> None:
        """Persist the edited settings and notify."""
        s = ctx.settings.load()
        s.provider = provider.value
        s.model = model_field.value
        s.base_url = base_field.value or ""
        s.api_key = api_field.value or ""
        s.language = language.value
        s.theme = theme.value
        s.user = user.value
        ctx.settings.save(s)
        i18n.set_language(s.language)
        _notify(page, i18n.tr("st.saved"))

    return _card(
        i18n.tr("st.title"),
        ft.Row([provider, model_field], spacing=12, wrap=True),
        ft.Row([base_field, api_field], spacing=12, wrap=True),
        ft.Row([language, theme, user], spacing=12, wrap=True),
        ft.Button(
            i18n.tr("common.save"), icon=ft.Icons.SAVE, on_click=save
        ),
    )
