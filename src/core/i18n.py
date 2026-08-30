"""Central i18n store (English / Chinese).

All UI strings live here so the two frontends (NiceGUI, Textual)
share one source of truth. Frontends call :func:`tr` with a dotted key;
the active language is set via :func:`set_language` (usually from the
persisted user settings on startup).
"""

from __future__ import annotations

from .constants import UI_LANGUAGES

_EN: dict[str, str] = {
    "app.name": "BabelDOC WebBox",
    "app.tagline": "PDF translation & LLM deployment toolkit",
    "nav.translate": "Translate",
    "nav.vram": "VRAM Calculator",
    "nav.settings": "Settings",
    "common.start": "Start",
    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.saved": "Saved",
    "common.error": "Error",
    "common.file": "File",
    "common.status": "Status",
    "common.progress": "Progress",
    "common.result": "Result",
    "common.details": "Details",
    "common.copy": "Copy",
    "common.copied": "Copied to clipboard",
    "common.refresh": "Refresh",
    "status.idle": "Idle",
    "status.running": "Running",
    "status.finished": "Finished",
    "status.error": "Failed",
    "status.cancelled": "Cancelled",
    "tr.title": "PDF Translation",
    "tr.upload": "Select a PDF file",
    "tr.upload_hint": "Drop a PDF here or click to browse",
    "tr.file_path": "PDF file path (TUI)",
    "tr.source_lang": "Source language",
    "tr.target_lang": "Target language",
    "tr.provider": "Provider",
    "tr.model": "Model",
    "tr.api_key": "API key",
    "tr.base_url": "Base URL",
    "tr.pages": "Pages (e.g. 1-5, empty = all)",
    "tr.dual": "Bilingual output",
    "tr.mono": "Monolingual output",
    "tr.qps": "QPS limit",
    "tr.output_dir": "Output directory (empty = default)",
    "tr.start_confirm": "Start translation?",
    "tr.no_file": "Please select a PDF file first",
    "tr.no_api_key": "Please provide an API key (or use Ollama locally)",
    "tr.stage": "Stage",
    "tr.result_file": "Translated file",
    "tr.download": "Download result",
    "tr.cancel_confirm": "Cancel this translation?",
    "vram.title": "LLM VRAM Calculator",
    "vram.model": "Model",
    "vram.preset": "Preset",
    "vram.custom": "Custom (manual params)",
    "vram.fetch_hf": "Fetch from HuggingFace",
    "vram.fetch_failed": "Could not fetch model config from HuggingFace",
    "vram.gpu": "GPU",
    "vram.mode": "Mode",
    "vram.mode.inference": "Inference",
    "vram.mode.training": "Training",
    "vram.mode.serving": "Serving (vLLM)",
    "vram.dtype": "Precision",
    "vram.batch": "Batch size",
    "vram.seq_len": "Sequence length",
    "vram.estimate": "Estimate",
    "vram.total": "Total VRAM",
    "vram.fits": "Fits",
    "vram.not_fits": "Does not fit",
    "vram.headroom": "Headroom",
    "vram.utilization": "GPU memory usage",
    "vram.lora": "LoRA fine-tuning",
    "vram.lora_rank": "LoRA rank",
    "vram.optimizer": "Optimizer",
    "vram.grad_ckpt": "Gradient checkpointing",
    "vram.ddp": "DDP (multi-GPU)",
    "vram.num_gpus": "GPU count",
    "vram.mixed_precision": "Mixed precision (FP32 master weights)",
    "vram.max_model_len": "Max model len",
    "vram.max_num_seqs": "Max concurrent sequences",
    "vram.gpu_mem_util": "GPU memory utilization",
    "vram.kv_dtype": "KV cache dtype",
    "vram.cuda_graphs": "CUDA graphs",
    "vram.max_seqs": "Max concurrent seqs (actual)",
    "vram.kv_per_token": "KV cache per token",
    "vram.kv_per_seq": "KV cache per sequence",
    "vram.prompt_tps": "Prompt throughput (est.)",
    "vram.gen_tps": "Generation throughput (est.)",
    "vram.vllm_cmd": "vLLM command",
    "vram.params_b": "Params (B)",
    "vram.hidden": "Hidden size",
    "vram.layers": "Layers",
    "vram.heads": "Attention heads",
    "vram.kv_heads": "KV heads",
    "vram.vocab": "Vocab size",
    "vram.intermediate": "Intermediate size",
    "vram.formula.title": "How this is calculated",
    "vram.formula.weights": "weights = params × bytes/param (all MoE experts loaded)",
    "vram.formula.kv": "kv/token = 2 × layers × kv_heads × head_dim × dtype_bytes",
    "vram.formula.act": "training activations scale with batch × seq² (attention scores)",
    "vram.formula.throughput": "throughput is a theoretical ceiling (compute/bandwidth bound)",
    "vram.need_manual": "Provide params/hidden/layers for custom models",
    "vram.breakdown": "Memory breakdown",
    "vram.notes": "Notes",
    "item.weights": "Model weights",
    "item.gradients": "Gradients",
    "item.optimizer": "Optimizer states",
    "item.activations": "Activations",
    "item.kv_cache": "KV cache",
    "item.ddp": "DDP overhead",
    "item.compile": "torch.compile",
    "item.cuda": "CUDA overhead",
    "item.overhead": "Overhead (CUDA graphs + padding)",
    "st.title": "Settings",
    "st.language": "Interface language",
    "st.theme": "Theme",
    "st.user": "User",
    "st.provider": "Default provider",
    "st.model": "Default model",
    "st.api_key": "API key",
    "st.base_url": "Base URL",
    "st.saved": "Settings saved",
    "st.user_switched": "Switched to user {user}",
    "st.theme_applied": "Theme applied",
    "st.lang_applied": "Language changed, reloading…",
}

_ZH: dict[str, str] = {
    "app.name": "BabelDOC WebBox",
    "app.tagline": "PDF 翻译与 LLM 部署工具",
    "nav.translate": "翻译",
    "nav.vram": "显存计算",
    "nav.settings": "设置",
    "common.start": "开始",
    "common.cancel": "取消",
    "common.save": "保存",
    "common.saved": "已保存",
    "common.error": "错误",
    "common.file": "文件",
    "common.status": "状态",
    "common.progress": "进度",
    "common.result": "结果",
    "common.details": "详情",
    "common.copy": "复制",
    "common.copied": "已复制到剪贴板",
    "common.refresh": "刷新",
    "status.idle": "空闲",
    "status.running": "运行中",
    "status.finished": "已完成",
    "status.error": "失败",
    "status.cancelled": "已取消",
    "tr.title": "PDF 翻译",
    "tr.upload": "选择 PDF 文件",
    "tr.upload_hint": "拖放 PDF 或点击选择",
    "tr.file_path": "PDF 文件路径（TUI）",
    "tr.source_lang": "源语言",
    "tr.target_lang": "目标语言",
    "tr.provider": "服务商",
    "tr.model": "模型",
    "tr.api_key": "API 密钥",
    "tr.base_url": "接口地址",
    "tr.pages": "页码（如 1-5，留空 = 全部）",
    "tr.dual": "双语输出",
    "tr.mono": "单语输出",
    "tr.qps": "QPS 限制",
    "tr.output_dir": "输出目录（留空 = 默认）",
    "tr.start_confirm": "开始翻译？",
    "tr.no_file": "请先选择 PDF 文件",
    "tr.no_api_key": "请填写 API 密钥（或使用本地 Ollama）",
    "tr.stage": "阶段",
    "tr.result_file": "翻译结果文件",
    "tr.download": "下载结果",
    "tr.cancel_confirm": "取消本次翻译？",
    "vram.title": "LLM 显存计算器",
    "vram.model": "模型",
    "vram.preset": "预设",
    "vram.custom": "自定义（手动参数）",
    "vram.fetch_hf": "从 HuggingFace 获取",
    "vram.fetch_failed": "无法从 HuggingFace 获取模型配置",
    "vram.gpu": "GPU",
    "vram.mode": "模式",
    "vram.mode.inference": "推理",
    "vram.mode.training": "训练",
    "vram.mode.serving": "部署 (vLLM)",
    "vram.dtype": "精度",
    "vram.batch": "批大小",
    "vram.seq_len": "序列长度",
    "vram.estimate": "估算",
    "vram.total": "总显存",
    "vram.fits": "可运行",
    "vram.not_fits": "显存不足",
    "vram.headroom": "余量",
    "vram.utilization": "显存占用率",
    "vram.lora": "LoRA 微调",
    "vram.lora_rank": "LoRA 秩",
    "vram.optimizer": "优化器",
    "vram.grad_ckpt": "梯度检查点",
    "vram.ddp": "DDP（多卡）",
    "vram.num_gpus": "GPU 数量",
    "vram.mixed_precision": "混合精度（FP32 主权重）",
    "vram.max_model_len": "最大上下文长度",
    "vram.max_num_seqs": "最大并发序列",
    "vram.gpu_mem_util": "显存利用率",
    "vram.kv_dtype": "KV 缓存精度",
    "vram.cuda_graphs": "CUDA 图",
    "vram.max_seqs": "实际最大并发序列",
    "vram.kv_per_token": "每 token KV 缓存",
    "vram.kv_per_seq": "每序列 KV 缓存",
    "vram.prompt_tps": "Prefill 吞吐（粗估）",
    "vram.gen_tps": "Decode 吞吐（粗估）",
    "vram.vllm_cmd": "vLLM 命令",
    "vram.params_b": "参数量 (B)",
    "vram.hidden": "隐藏层维度",
    "vram.layers": "层数",
    "vram.heads": "注意力头",
    "vram.kv_heads": "KV 头",
    "vram.vocab": "词表大小",
    "vram.intermediate": "中间层维度",
    "vram.formula.title": "计算说明",
    "vram.formula.weights": "权重 = 参数量 × 每参数字节（MoE 加载全部专家）",
    "vram.formula.kv": "每 token KV = 2 × 层数 × KV头 × head_dim × 精度字节",
    "vram.formula.act": "训练激活显存随 批大小 × 序列长度² 增长（注意力分数）",
    "vram.formula.throughput": "吞吐为理论上限（受算力/带宽限制）",
    "vram.need_manual": "自定义模型需填写 参数量/隐藏层/层数",
    "vram.breakdown": "显存分解",
    "vram.notes": "提示",
    "item.weights": "模型权重",
    "item.gradients": "梯度",
    "item.optimizer": "优化器状态",
    "item.activations": "激活值",
    "item.kv_cache": "KV 缓存",
    "item.ddp": "DDP 开销",
    "item.compile": "torch.compile",
    "item.cuda": "CUDA 开销",
    "item.overhead": "开销（CUDA 图 + 预留）",
    "st.title": "设置",
    "st.language": "界面语言",
    "st.theme": "主题",
    "st.user": "用户",
    "st.provider": "默认服务商",
    "st.model": "默认模型",
    "st.api_key": "API 密钥",
    "st.base_url": "接口地址",
    "st.saved": "设置已保存",
    "st.user_switched": "已切换到用户 {user}",
    "st.theme_applied": "主题已应用",
    "st.lang_applied": "语言已切换，正在重载…",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {"en": _EN, "zh": _ZH}

_current_language: str = "en"


def set_language(language: str) -> None:
    """Set the active UI language.

    Args:
        language: Language code (``en`` or ``zh``). Unknown codes fall back
            to English silently.
    """
    global _current_language
    _current_language = language if language in _TRANSLATIONS else "en"


def get_language() -> str:
    """Return the active UI language code."""
    return _current_language


def tr(key: str, **kwargs: object) -> str:
    """Translate a dotted key in the active language.

    Args:
        key: Dotted i18n key, e.g. ``tr.title``.
        **kwargs: Format placeholders for ``str.format`` (e.g. ``user='bob'``).

    Returns:
        The translated string. Missing keys return the key itself so UI
        gaps are visible instead of blank.
    """
    table = _TRANSLATIONS.get(_current_language, _TRANSLATIONS["en"])
    text = table.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def languages() -> dict[str, str]:
    """Return the supported UI languages as ``{code: display_name}``."""
    return dict(UI_LANGUAGES)

