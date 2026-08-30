"""Unit tests for the VRAM estimation service (pure CPU math)."""

import pytest

from src.modules.vram.models import VramRequest
from src.modules.vram.service import VramService


@pytest.fixture()
def svc() -> VramService:
    """A fresh VramService instance."""
    return VramService()


def test_inference_7b_fits_a100_80g(svc: VramService) -> None:
    """BF16 7B inference on an A100 80G must fit with a full breakdown."""
    est = svc.estimate(
        VramRequest(
            model_id="Qwen2.5-7B", gpu="A100 80G", mode="inference",
            dtype="BF16", batch_size=1, seq_length=2048,
        )
    )
    assert est.fits
    assert est.total_gb > 14  # BF16 weights alone are ~15 GiB
    keys = {it.key for it in est.items}
    assert {"item.weights", "item.kv_cache", "item.activations", "item.cuda"} <= keys
    assert est.vllm_command == ""
    assert est.utilization_pct < 100


def test_inference_70b_does_not_fit_3090(svc: VramService) -> None:
    """A 70B model in BF16 cannot fit a 24G card."""
    est = svc.estimate(
        VramRequest(model_id="Llama-3.1-70B", gpu="RTX 3090 24G",
                    mode="inference", dtype="BF16")
    )
    assert not est.fits
    assert est.total_gb > 24
    assert est.headroom_gb < 0


def test_training_full_7b_exceeds_24g(svc: VramService) -> None:
    """Full fine-tuning of 7B needs gradients + optimizer state."""
    est = svc.estimate(
        VramRequest(
            model_id="Qwen2.5-7B", gpu="RTX 3090 24G", mode="training",
            dtype="BF16", batch_size=1, seq_length=1024, lora=False,
            mixed_precision=True,
        )
    )
    assert not est.fits
    keys = {it.key for it in est.items}
    assert {"item.gradients", "item.optimizer", "item.activations"} <= keys


def test_lora_training_7b_fits_24g(svc: VramService) -> None:
    """LoRA fine-tuning only trains adapters, so it fits a 24G card."""
    est = svc.estimate(
        VramRequest(
            model_id="Qwen2.5-7B", gpu="RTX 3090 24G", mode="training",
            dtype="BF16", batch_size=1, seq_length=1024, lora=True,
            lora_rank=8, mixed_precision=True, gradient_checkpointing=True,
        )
    )
    assert est.fits
    grads = next(it for it in est.items if it.key == "item.gradients")
    assert grads.gb < 1.0  # only LoRA adapters, not the full model


def test_moe_serving_tp2(svc: VramService) -> None:
    """MoE serving with TP=2: per-GPU total fits, vLLM command produced."""
    est = svc.estimate(
        VramRequest(
            model_id="Qwen3-30B-A3B", gpu="A100 80G", mode="serving",
            dtype="BF16", num_gpus=2, max_model_len=32768, max_num_seqs=64,
        )
    )
    assert est.fits
    assert est.total_gb < 80  # per-GPU total
    assert est.max_seqs > 0
    assert est.gen_tps > 0
    assert est.kv_per_token_kb > 0
    assert est.vllm_command.startswith("vllm serve Qwen3-30B-A3B")
    assert "--tensor-parallel-size 2" in est.vllm_command


def test_serving_tp_head_imbalance_note(svc: VramService) -> None:
    """TP=3 on a 4-KV-head model must warn about uneven head split."""
    est = svc.estimate(
        VramRequest(model_id="Qwen2.5-7B", gpu="A100 80G", mode="serving",
                    dtype="BF16", num_gpus=3)
    )
    assert any("evenly" in note for note in est.notes)


def test_unknown_model_raises(svc: VramService) -> None:
    """Unknown model without manual params raises ValueError."""
    with pytest.raises(ValueError, match="Unknown model"):
        svc.estimate(
            VramRequest(model_id="no/such-model-xyz", gpu="A100 80G",
                        mode="inference", dtype="BF16")
        )


def test_manual_model_params(svc: VramService) -> None:
    """Manual params build a working custom model spec."""
    est = svc.estimate(
        VramRequest(
            model_id="my/custom-model", gpu="A100 80G", mode="inference",
            dtype="BF16", manual_params_b=7.6, manual_hidden=3584,
            manual_layers=28, manual_heads=28, manual_kv_heads=4,
            manual_vocab=151936, manual_intermediate=18944,
        )
    )
    assert est.fits
    assert est.total_gb > 14


def test_estimate_params_from_config() -> None:
    """estimate_params approximates Qwen2.5-7B (~7.6B) from a HF config."""
    b = VramService.estimate_params(
        {
            "num_hidden_layers": 28,
            "hidden_size": 3584,
            "num_attention_heads": 28,
            "num_key_value_heads": 4,
            "intermediate_size": 18944,
            "vocab_size": 151936,
        }
    )
    assert b is not None
    assert 7.0 < b < 9.5


def test_estimate_params_missing_fields() -> None:
    """Configs without hidden_size/num_hidden_layers yield None."""
    assert VramService.estimate_params({}) is None
