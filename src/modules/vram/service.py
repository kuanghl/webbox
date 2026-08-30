"""VRAM estimation engine.

Pure-function core (no I/O except the optional HuggingFace fetch) so it is
trivially unit-testable. Formula sources:

* training / inference: ``docs/refer-llm-vram-calc.md``
* serving (vLLM): ``docs/refer-vllm-vram-calc.md``
* throughput ceilings: ``docs/refer-llm-gpu-vram-calculator.md``
"""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from .interfaces import VramCalculator
from .models import (
    COMPILE_FRACTION,
    CUDA_GRAPHS_GB,
    CUDA_OVERHEAD_GB,
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
    BreakdownItem,
    ModelSpec,
    VramEstimate,
    VramRequest,
)

logger = logging.getLogger(__name__)

_GIB = 1024**3
_HF_CONFIG_URL = "https://huggingface.co/{model_id}/resolve/main/config.json"
_LORA_TARGET_MODULES = 7  # q, k, v, o, gate, up, down


class VramService(VramCalculator):
    """Concrete VRAM estimator over the built-in model/GPU catalogs."""

    def estimate(self, request: VramRequest) -> VramEstimate:
        """Estimate VRAM for a request.

        Args:
            request: Model, GPU and workload parameters.

        Returns:
            The estimate with per-item breakdown.

        Raises:
            ValueError: When required parameters are missing or invalid.
        """
        if request.mode not in ("inference", "training", "serving"):
            raise ValueError(f"Unknown mode: {request.mode}")
        gpu = GPU_SPECS.get(request.gpu)
        if gpu is None:
            raise ValueError(f"Unknown GPU: {request.gpu}")
        spec = self._resolve_model(request)

        if request.mode == "serving":
            return self._estimate_serving(request, spec, gpu)
        return self._estimate_local(request, spec, gpu)

    def _resolve_model(self, request: VramRequest) -> ModelSpec:
        """Resolve a request to a :class:`ModelSpec`.

        Resolution order: preset exact → preset suffix (HF id) → manual
        params. Raises when nothing usable is available.
        """
        model_id = request.model_id.strip()
        if model_id in MODEL_PRESETS:
            return MODEL_PRESETS[model_id]
        if "/" in model_id:
            suffix = model_id.rsplit("/", 1)[-1]
            for name, spec in MODEL_PRESETS.items():
                if name.lower() == suffix.lower():
                    return spec
        if request.manual_params_b > 0 and request.manual_hidden > 0 and request.manual_layers > 0:
            return ModelSpec(
                name=model_id or "custom",
                params_b=request.manual_params_b,
                hidden=request.manual_hidden,
                layers=request.manual_layers,
                heads=request.manual_heads or 32,
                kv_heads=request.manual_kv_heads or 8,
                vocab_size=request.manual_vocab or 32000,
                intermediate_size=request.manual_intermediate or 4 * request.manual_hidden,
            )
        raise ValueError(
            "Unknown model. Pick a preset or provide params_b/hidden/layers "
            "(or a fetchable HuggingFace id)."
        )

    async def fetch_model_config(self, model_id: str) -> dict | None:
        """Fetch a model config (HuggingFace) for preset-less models.

        Args:
            model_id: HuggingFace repo id, e.g. ``Qwen/Qwen2.5-7B-Instruct``.

        Returns:
            Parsed config dict, or ``None`` when unavailable.
        """
        url = _HF_CONFIG_URL.format(model_id=model_id)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("HuggingFace config fetch failed for %s: %s", model_id, exc)
            return None

    @staticmethod
    def estimate_params(config: dict[str, Any]) -> float | None:
        """Estimate total parameters (billions) from a HF config dict.

        Uses the standard dense-transformer approximation
        (attention + FFN + embeddings). Returns ``None`` when the config
        lacks the required fields.
        """
        hidden = config.get("hidden_size") or config.get("d_model")
        layers = config.get("num_hidden_layers") or config.get("num_layers")
        if not hidden or not layers:
            return None
        vocab = config.get("vocab_size", 32000)
        intermediate = config.get("intermediate_size", 4 * hidden)
        per_layer = 4 * hidden**2 + 3 * hidden * intermediate
        total = layers * per_layer + 2 * vocab * hidden
        return total / 1e9

    # ------------------------------------------------------------------
    # inference / training (single GPU, llm-vram-calc formulas)
    # ------------------------------------------------------------------
    def _estimate_local(
        self, request: VramRequest, spec: ModelSpec, gpu: Any
    ) -> VramEstimate:
        """Compute inference or training VRAM on one GPU."""
        bpp = DTYPE_BYTES.get(request.dtype, 2.0)
        params_b = spec.params_b
        is_moe = spec.num_experts > 1
        if is_moe:
            active_params_b = spec.active_params_b or params_b * (
                0.33 + 0.67 * spec.experts_per_token / spec.num_experts
            )
        else:
            active_params_b = params_b
        head_dim = spec.hidden // spec.heads if spec.heads else 128
        training = request.mode == "training"

        items: list[BreakdownItem] = []
        # 1. weights (all MoE experts are loaded)
        weights_gb = params_b * 1e9 * bpp / _GIB
        items.append(BreakdownItem(ITEM_WEIGHTS, weights_gb))

        notes: list[str] = []
        gradients_gb = 0.0
        ddp_gb = 0.0
        if training:
            # trainable params: LoRA adapters or full model
            if request.lora:
                lora_params = (
                    request.lora_rank * spec.hidden * 2 * _LORA_TARGET_MODULES * spec.layers
                )
                trainable_b = lora_params / 1e9
            else:
                trainable_b = params_b
            mixed = request.mixed_precision
            if mixed:
                gradients_gb = trainable_b * 1e9 * 2 / _GIB
                master_gb = trainable_b * 1e9 * 4 / _GIB
            else:
                gradients_gb = trainable_b * 1e9 * bpp / _GIB
                master_gb = 0.0
            items.append(BreakdownItem(ITEM_GRADIENTS, gradients_gb))
            optimizer_gb = (
                trainable_b * 1e9 * OPTIMIZER_BYTES.get(request.optimizer, 8.0) / _GIB
            )
            optimizer_gb += master_gb
            items.append(BreakdownItem(ITEM_OPTIMIZER, optimizer_gb))
            if request.ddp:
                grad_buf = trainable_b * 1e9 * (2.0 if mixed else bpp) / _GIB
                ddp_gb = grad_buf + (0.05 + 0.02 * grad_buf)
                items.append(BreakdownItem(ITEM_DDP, ddp_gb))

        # 4. activations (fp16/bf16 activations)
        b, s, h = request.batch_size, request.seq_length, spec.hidden
        x = b * s * h * 2
        if training:
            if request.gradient_checkpointing:
                eff_layers = max(1, int(math.sqrt(spec.layers)))
            else:
                eff_layers = spec.layers
            attn_gb = eff_layers * (x + 3 * x + b * spec.heads * s * s * 2 + x) / _GIB
            eff_inter = (
                spec.intermediate_size * spec.experts_per_token
                if is_moe
                else spec.intermediate_size
            )
            ffn_gb = eff_layers * (x + 3 * b * s * eff_inter * 2) / _GIB
            if is_moe:
                ffn_gb += eff_layers * b * s * spec.num_experts * 2 / _GIB
            other_gb = (eff_layers * 4 * x + x) / _GIB
            activations_gb = attn_gb + ffn_gb + other_gb
        else:
            activations_gb = (x + b * s * spec.intermediate_size * 2 + x) / _GIB
        items.append(BreakdownItem(ITEM_ACTIVATIONS, activations_gb))

        # 5. KV cache (inference only)
        if not training:
            kv_gb = 2 * b * spec.layers * s * spec.kv_heads * head_dim * bpp / _GIB
            items.append(BreakdownItem(ITEM_KV_CACHE, kv_gb))

        if request.torch_compile:
            items.append(BreakdownItem(ITEM_COMPILE, COMPILE_FRACTION * weights_gb))
        items.append(BreakdownItem(ITEM_CUDA, CUDA_OVERHEAD_GB))

        if is_moe and training and not request.lora:
            notes.append(
                f"MoE: all {spec.num_experts} experts are updated in full "
                f"fine-tuning; active params (~{active_params_b:.1f}B) only "
                f"affect compute, not memory."
            )
        if not training and s > 8192:
            notes.append("Long context: KV cache dominates; consider GQA/MLA or fp8 KV.")

        total_gb = sum(i.gb for i in items)
        return self._finish(total_gb, gpu.vram_gb, items, notes)

    # ------------------------------------------------------------------
    # serving (vLLM, vllm-vram-calc formulas)
    # ------------------------------------------------------------------
    def _estimate_serving(
        self, request: VramRequest, spec: ModelSpec, gpu: Any
    ) -> VramEstimate:
        """Compute per-GPU VRAM for a vLLM deployment with tensor parallelism."""
        n = max(1, request.num_gpus)
        bpp = DTYPE_BYTES.get(request.dtype, 2.0)
        kv_bpp = 1.0 if request.kv_cache_dtype == "fp8" else bpp
        head_dim = spec.hidden // spec.heads if spec.heads else 128
        is_moe = spec.num_experts > 1
        if is_moe:
            active_params_b = spec.active_params_b or spec.params_b * (
                0.33 + 0.67 * spec.experts_per_token / spec.num_experts
            )
        else:
            active_params_b = spec.params_b

        available_gb = gpu.vram_gb * request.gpu_memory_utilization
        weights_gb = spec.params_b * 1e9 * bpp / _GIB / n
        cuda_graphs_gb = CUDA_GRAPHS_GB if request.cuda_graphs else 0.0
        overhead_gb = request.overhead_padding_gb

        kv_heads_per_gpu = math.ceil(spec.kv_heads / n)
        kv_bytes_token = 2 * kv_heads_per_gpu * head_dim * kv_bpp * spec.layers
        kv_bytes_seq = kv_bytes_token * request.max_model_len

        notes: list[str] = []
        kv_available = available_gb * _GIB - (weights_gb + cuda_graphs_gb + overhead_gb) * _GIB
        items = [
            BreakdownItem(ITEM_WEIGHTS, weights_gb),
            BreakdownItem(ITEM_OVERHEAD, cuda_graphs_gb + overhead_gb),
        ]

        if kv_available <= 0:
            items.append(BreakdownItem(ITEM_KV_CACHE, 0.0))
            notes.append(
                "Model weights exceed the per-GPU budget. Add GPUs or lower "
                "the memory utilization."
            )
            total_gb = weights_gb + cuda_graphs_gb + overhead_gb
            return self._finish(total_gb, gpu.vram_gb, items, notes, over=True)

        max_tokens = int(kv_available / kv_bytes_token)
        max_seqs_by_kv = max(0, max_tokens // request.max_model_len)
        actual_seqs = min(max_seqs_by_kv, request.max_num_seqs)
        kv_gb = actual_seqs * kv_bytes_seq / _GIB
        items.append(BreakdownItem(ITEM_KV_CACHE, kv_gb))

        if actual_seqs < request.max_num_seqs:
            notes.append(
                f"KV cache fits only {actual_seqs} of the requested "
                f"{request.max_num_seqs} sequences; reduce max_model_len "
                "or add GPUs."
            )
        if kv_heads_per_gpu * n > spec.kv_heads:
            notes.append(
                f"TP={n} does not divide {spec.kv_heads} KV heads evenly; "
                f"some GPUs carry {kv_heads_per_gpu} heads."
            )

        # theoretical throughput ceilings (llm-gpu-vram-calculator)
        active_bytes = active_params_b * 1e9 * bpp / n
        prompt_tps = gpu.tflops_fp16 * 1e12 / (2 * spec.params_b * 1e9) / n
        gen_tps = (gpu.bandwidth_gbps * 1e9 / active_bytes) if active_bytes > 0 else 0.0

        total_gb = weights_gb + cuda_graphs_gb + overhead_gb + kv_gb
        est = self._finish(total_gb, gpu.vram_gb, items, notes)
        est.kv_per_token_kb = kv_bytes_token / 1024
        est.kv_per_seq_gb = kv_bytes_seq / _GIB
        est.max_seqs = actual_seqs
        est.prompt_tps = prompt_tps
        est.gen_tps = gen_tps
        est.vllm_command = self._vllm_command(request, spec, actual_seqs)
        return est

    @staticmethod
    def _vllm_command(request: VramRequest, spec: ModelSpec, actual_seqs: int) -> str:
        """Build a ready-to-run ``vllm serve`` command."""
        model = request.model_id or spec.name
        parts = [
            "vllm serve", model,
            f"--tensor-parallel-size {max(1, request.num_gpus)}",
            f"--max-model-len {request.max_model_len}",
            f"--max-num-seqs {actual_seqs}",
            f"--gpu-memory-utilization {request.gpu_memory_utilization}",
            f"--dtype {request.dtype.lower()}",
        ]
        if request.kv_cache_dtype == "fp8":
            parts.append("--kv-cache-dtype fp8")
        return " ".join(parts)

    @staticmethod
    def _finish(
        total_gb: float,
        gpu_vram_gb: float,
        items: list[BreakdownItem],
        notes: list[str],
        over: bool = False,
    ) -> VramEstimate:
        """Assemble the final estimate with utilization and fit flags."""
        fits = (not over) and total_gb <= gpu_vram_gb
        utilization = min(100.0, total_gb / gpu_vram_gb * 100.0) if gpu_vram_gb else 0.0
        if fits and utilization > 95.0:
            notes.append("Memory usage above 95%; leave headroom for safety.")
        return VramEstimate(
            total_gb=round(total_gb, 2),
            gpu_vram_gb=gpu_vram_gb,
            fits=fits,
            utilization_pct=round(utilization, 1),
            headroom_gb=round(gpu_vram_gb - total_gb, 2),
            items=tuple(items),
            notes=notes,
        )
