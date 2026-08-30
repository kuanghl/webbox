"""Data types and reference data for the VRAM module.

Formulas and data tables follow ``docs/refer-llm-vram-calc.md`` (training /
inference) and ``docs/refer-vllm-vram-calc.md`` (serving). All sizes use
binary GiB (1024**3 bytes) and are labeled as such in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bytes per parameter for each supported precision.
DTYPE_BYTES: dict[str, float] = {
    "BF16": 2.0,
    "FP16": 2.0,
    "FP8": 1.0,
    "INT8": 1.0,
    "INT4": 0.5,
    "FP32": 4.0,
}

#: Optimizer state cost in bytes per trainable parameter.
OPTIMIZER_BYTES: dict[str, float] = {
    "AdamW (32-bit)": 8.0,
    "AdamW (8-bit)": 2.0,
    "SGD": 4.0,
    "Adafactor": 2.0,
}

#: CUDA context / runtime constant overhead (GiB).
CUDA_OVERHEAD_GB: float = 0.5
#: torch.compile workspace overhead as a fraction of weights.
COMPILE_FRACTION: float = 0.1
#: CUDA graph capture cost per GPU (GiB), vllm-vram-calc constant.
CUDA_GRAPHS_GB: float = 2.5


@dataclass(frozen=True)
class GpuSpec:
    """Static GPU hardware spec.

    Attributes:
        name: Display name (also the selection key).
        vram_gb: Total VRAM in GiB.
        bandwidth_gbps: Memory bandwidth in GB/s.
        tflops_fp16: Dense FP16/BF16 throughput in TFLOPS.
    """

    name: str
    vram_gb: float
    bandwidth_gbps: float
    tflops_fp16: float


GPU_SPECS: dict[str, GpuSpec] = {
    spec.name: spec
    for spec in (
        GpuSpec("RTX 3060 Ti 8G", 8, 320, 44.4),
        GpuSpec("RTX 3090 24G", 24, 936, 142.0),
        GpuSpec("RTX 4090 24G", 24, 1008, 82.6),
        GpuSpec("T4 16G", 16, 320, 65.0),
        GpuSpec("A10G 24G", 24, 600, 31.2),
        GpuSpec("V100 16G", 16, 900, 125.0),
        GpuSpec("V100 32G", 32, 900, 125.0),
        GpuSpec("A6000 48G", 48, 768, 38.7),
        GpuSpec("L40S 48G", 48, 864, 362.0),
        GpuSpec("A100 40G", 40, 1555, 312.0),
        GpuSpec("A100 80G", 80, 2039, 312.0),
        GpuSpec("H100 SXM 80G", 80, 3350, 989.0),
        GpuSpec("H100 NVL 94G", 94, 3900, 989.0),
        GpuSpec("H200 141G", 141, 4800, 989.0),
        GpuSpec("B200 192G", 192, 8000, 2250.0),
    )
}


@dataclass(frozen=True)
class ModelSpec:
    """Static model architecture spec.

    Attributes:
        name: Display name (also the selection key).
        params_b: Total parameters in billions.
        hidden: Hidden layer width.
        layers: Number of transformer layers.
        heads: Number of attention heads.
        kv_heads: Number of KV heads (GQA/MQA aware).
        vocab_size: Token vocabulary size.
        intermediate_size: FFN intermediate width.
        num_experts: MoE expert count (1 = dense).
        experts_per_token: MoE experts activated per token.
        active_params_b: MoE active parameters in billions (0 = estimate).
        source: Optional citation for the numbers.
    """

    name: str
    params_b: float
    hidden: int
    layers: int
    heads: int
    kv_heads: int
    vocab_size: int
    intermediate_size: int
    num_experts: int = 1
    experts_per_token: int = 1
    active_params_b: float = 0.0
    source: str = ""


MODEL_PRESETS: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        # Llama family
        ModelSpec("Llama-3.2-1B", 1.2, 2048, 16, 32, 8, 128256, 6144),
        ModelSpec("Llama-3.2-3B", 3.2, 3072, 28, 24, 8, 128256, 8192),
        ModelSpec("Llama-3.1-8B", 8.0, 4096, 32, 32, 8, 128256, 14336),
        ModelSpec("Llama-3.1-70B", 70.0, 8192, 80, 64, 8, 128256, 28672),
        ModelSpec("Llama-3.3-70B", 70.0, 8192, 80, 64, 8, 128256, 28672),
        ModelSpec("Mistral-7B-v0.3", 7.2, 4096, 32, 32, 8, 32768, 14336),
        ModelSpec("Mixtral-8x7B", 46.7, 4096, 32, 32, 8, 32000, 14336,
                  num_experts=8, experts_per_token=2, active_params_b=12.9),
        # Qwen family
        ModelSpec("Qwen2.5-0.5B", 0.5, 896, 24, 14, 2, 151936, 4864),
        ModelSpec("Qwen2.5-1.5B", 1.5, 1536, 28, 12, 2, 151936, 8960),
        ModelSpec("Qwen2.5-3B", 3.1, 2048, 36, 16, 2, 151936, 11008),
        ModelSpec("Qwen2.5-7B", 7.6, 3584, 28, 28, 4, 151936, 18944),
        ModelSpec("Qwen2.5-14B", 14.8, 5120, 48, 40, 8, 151936, 27648),
        ModelSpec("Qwen2.5-32B", 32.8, 5120, 64, 40, 8, 151936, 27648),
        ModelSpec("Qwen3-8B", 8.2, 4096, 36, 32, 8, 151936, 12288),
        ModelSpec("Qwen3-30B-A3B", 30.5, 2048, 48, 32, 4, 151936, 768,
                  num_experts=128, experts_per_token=8, active_params_b=3.3),
        ModelSpec("Qwen3-235B-A22B", 235.0, 4096, 94, 64, 4, 151936, 12288,
                  num_experts=128, experts_per_token=8, active_params_b=22.0),
        # DeepSeek family (MLA approximated as standard MHA for estimation)
        ModelSpec("DeepSeek-V3", 671.0, 7168, 61, 128, 128, 129280, 18432,
                  num_experts=256, experts_per_token=8, active_params_b=37.0,
                  source="DeepSeek-V3 Technical Report (arXiv:2412.19437)"),
        ModelSpec("DeepSeek-R1", 671.0, 7168, 61, 128, 128, 129280, 18432,
                  num_experts=256, experts_per_token=8, active_params_b=37.0,
                  source="DeepSeek-R1 paper (arXiv:2501.12948)"),
        # Gemma family
        ModelSpec("Gemma-3-4B", 4.3, 2560, 34, 32, 16, 262208, 16384),
        ModelSpec("Gemma-3-12B", 12.4, 3840, 48, 32, 16, 262208, 25600),
        ModelSpec("Gemma-3-27B", 27.0, 5376, 62, 32, 16, 262208, 32768),
    )
}

#: Breakdown item i18n keys (see ``src.core.i18n``).
ITEM_WEIGHTS = "item.weights"
ITEM_GRADIENTS = "item.gradients"
ITEM_OPTIMIZER = "item.optimizer"
ITEM_ACTIVATIONS = "item.activations"
ITEM_KV_CACHE = "item.kv_cache"
ITEM_DDP = "item.ddp"
ITEM_COMPILE = "item.compile"
ITEM_CUDA = "item.cuda"
ITEM_OVERHEAD = "item.overhead"


@dataclass
class BreakdownItem:
    """One line of the VRAM breakdown.

    Attributes:
        key: i18n key of the item name.
        gb: Size in GiB.
    """

    key: str
    gb: float


@dataclass
class VramRequest:
    """All inputs for one estimation.

    Attributes:
        model_id: Preset key or HuggingFace repo id (empty = manual).
        gpu: GPU spec name.
        mode: ``inference`` | ``training`` | ``serving``.
        dtype: Weight precision (see :data:`DTYPE_BYTES`).
        batch_size: Batch size (inference/training).
        seq_length: Sequence length (inference/training).
        manual_params_b: Manual total params in billions (0 = auto).
        manual_hidden: Manual hidden size (0 = auto).
        manual_layers: Manual layer count (0 = auto).
        manual_heads: Manual attention heads (0 = auto).
        manual_kv_heads: Manual KV heads (0 = auto).
        manual_vocab: Manual vocab size (0 = auto).
        manual_intermediate: Manual FFN intermediate size (0 = auto).
        lora: Enable LoRA fine-tuning (training).
        lora_rank: LoRA rank.
        optimizer: Optimizer name (see :data:`OPTIMIZER_BYTES`).
        gradient_checkpointing: Use activation checkpointing (training).
        ddp: Multi-GPU DDP overhead (training).
        mixed_precision: FP32 master weights (training).
        torch_compile: Add torch.compile overhead.
        num_gpus: Tensor-parallel GPU count (serving).
        max_model_len: Max context length (serving).
        max_num_seqs: Requested max concurrent sequences (serving).
        gpu_memory_utilization: vLLM ``gpu_memory_utilization`` (serving).
        kv_cache_dtype: ``auto`` (same as weights) or ``fp8`` (serving).
        cuda_graphs: Count CUDA graph capture memory (serving).
        overhead_padding_gb: Extra padding in GiB (serving).
    """

    model_id: str = "Qwen2.5-7B"
    gpu: str = "A100 80G"
    mode: str = "inference"
    dtype: str = "BF16"
    batch_size: int = 1
    seq_length: int = 2048
    manual_params_b: float = 0.0
    manual_hidden: int = 0
    manual_layers: int = 0
    manual_heads: int = 0
    manual_kv_heads: int = 0
    manual_vocab: int = 0
    manual_intermediate: int = 0
    lora: bool = False
    lora_rank: int = 8
    optimizer: str = "AdamW (32-bit)"
    gradient_checkpointing: bool = False
    ddp: bool = False
    mixed_precision: bool = False
    torch_compile: bool = False
    num_gpus: int = 1
    max_model_len: int = 4096
    max_num_seqs: int = 16
    gpu_memory_utilization: float = 0.9
    kv_cache_dtype: str = "auto"
    cuda_graphs: bool = True
    overhead_padding_gb: float = 1.0


@dataclass
class VramEstimate:
    """Estimation result with breakdown and serving extras.

    Attributes:
        total_gb: Estimated total VRAM in GiB.
        gpu_vram_gb: Per-GPU VRAM of the selected GPU.
        fits: Whether the workload fits in one GPU (inference/training)
            or per-GPU budget (serving).
        utilization_pct: 0-100 memory usage percentage.
        headroom_gb: Free GiB (negative when not fitting).
        items: Ordered breakdown items.
        notes: Human-readable warnings (already i18n-free, UI translates).
        kv_per_token_kb: KV cache bytes per token / 1024 (serving).
        kv_per_seq_gb: KV cache per full sequence (serving).
        max_seqs: Actual max concurrent sequences (serving).
        prompt_tps: Theoretical prefill tokens/s (serving).
        gen_tps: Theoretical decode tokens/s (serving).
        vllm_command: Ready-to-run ``vllm serve`` command (serving).
    """

    total_gb: float
    gpu_vram_gb: float
    fits: bool
    utilization_pct: float
    headroom_gb: float
    items: tuple[BreakdownItem, ...] = field(default_factory=tuple)
    notes: list[str] = field(default_factory=list)
    kv_per_token_kb: float = 0.0
    kv_per_seq_gb: float = 0.0
    max_seqs: int = 0
    prompt_tps: float = 0.0
    gen_tps: float = 0.0
    vllm_command: str = ""
