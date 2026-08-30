# Refer: llm-vram-calc (refers/llm-vram-calc)

> 参考来源：`refers/llm-vram-calc/vram_calculator.py`（1624 行，单文件 Python + Gradio）。
> **本项目 `src/modules/vram/` 计算引擎的主要参照**：GPU/精度/模型数据表、
> 训练/推理显存公式、分解（breakdown）结构均按此设计移植（公式为通用公开公式，代码重写）。

## 1. 定位

估算 LLM **训练（全参/LoRA）与推理**单卡显存需求的完整工具，支持 dense 与 MoE 架构，
输出逐项分解。Gradio UI 部分不采用（webbox 自建三端 UI），**只移植计算核心**。

## 2. 核心接口

```python
GPU_SPECS: dict[str, dict]            # 15 款 GPU: {"vram_gb": float, "bandwidth_gbps": float}
DTYPE_BYTES: dict[str, float]         # BF16/FP16=2, FP32=4, INT8=1, INT4=0.5
MODEL_PRESETS: dict[str, dict]        # 常见模型: params_b, hidden, layers, heads, kv_heads,
                                      # (MoE: active_params_b, num_experts, experts_per_token)

@dataclass
class VRAMEstimate:                   # 结果：weights/gradients/optimizer/activations/kv/
                                      # ddp/compile/cuda 各项 + total/peak/fits/utilization_pct/breakdown

def fetch_model_config(model_id: str) -> Optional[dict]   # 从 HuggingFace 拉 config.json
def estimate_params_from_config(config: dict) -> Optional[float]  # 按结构估算参数量(B)
def calculate_vram(model_id, gpu_name, mode, dtype, batch_size, seq_length,
                   gradient_checkpointing, optimizer, lora_rank, lora_enabled,
                   use_torch_compile=False, ddp_enabled=False, mixed_precision=False,
                   manual_*=0) -> Optional[VRAMEstimate]   # 核心引擎
```

模型解析顺序（`calculate_vram` 内）：
1. 预设精确匹配（忽略大小写）→ 2. 预设 `/` 后模型名匹配 → 3. HF 拉取 → 4. 手动参数
   （`manual_params_b/hidden/layers` 齐全即可离线计算）；都不满足返回 `None`。

## 3. 计算公式（webbox 移植基准，GB 均按 1024³ 字节）

记 `bpp = DTYPE_BYTES[dtype]`，`head_dim = hidden // heads`，`B = params_b * 1e9`。

```
# MoE
is_moe = num_experts > 1
active_params_b = B 侧: params_b * (0.33 + 0.67 * experts_per_token / num_experts)  # MoE 估算

# 1. 权重（MoE 全部专家都要加载 → 用总参数量）
weights = B * bpp

# 可训练参数
LoRA 训练: trainable = lora_rank * hidden * 2 * 7 * layers / 1e9   # 7 个目标模块 q/k/v/o/gate/up/down
全参:      trainable = params_b

# 2. 梯度（仅训练）
混合精度: gradients = trainable*1e9 * 2;  master_weights = trainable*1e9 * 4
全精度:   gradients = trainable*1e9 * bpp; master = 0

# 3. 优化器状态（仅训练，按可训练参数）
AdamW 32-bit: 8 B/param | AdamW 8-bit: 2 | SGD: 4 | Adafactor: 2
optimizer_states += master_weights

# 3.5 DDP（训练且多卡）
grad_buffer = trainable*1e9 * (2 if 混合精度 else bpp)
ddp = grad_buffer + (0.05 + 0.02 * grad_buffer)        # 桶开销

# 4. 激活（bytes_activation = 2，即 fp16/bf16 激活）
训练: effective_layers = sqrt(layers) if 梯度检查点 else layers
  attn  = eff_layers * (x + 3x + b*h*s² + x)            # x = b*s*hidden*2
  ffn   = eff_layers * (x + 3*eff_inter)                # SwiGLU: gate/up/intermediate
          MoE: eff_inter = intermediate * experts_per_token; 另加 router b*s*num_experts
  other = eff_layers * 4x + x                            # layernorm+residual+embedding
推理: attn = b*s*hidden*2; ffn = b*s*intermediate*2; other = b*s*hidden*2（均 /1024³）

# 5. KV 缓存（仅推理）
kv = 2 * batch * layers * seq * kv_heads * head_dim * bpp
kv_per_token = 2 * batch * layers * kv_heads * head_dim * bpp

# 6. torch.compile 开销 = 0.1 * weights（可选开关）
# 7. CUDA 上下文开销 = 0.5 GB（常数）

total = weights + gradients + optimizer + activations + kv + ddp + compile + cuda
fits  = total <= gpu.vram_gb
```

## 4. 内置数据（可整体借鉴）

- **GPU_SPECS（15 款）**：RTX 3060 Ti 8G / 3090 24G / 4090 24G / A10G 24G / T4 16G /
  V100 16G/32G / A6000 48G / L40S 48G / A100 40G/80G / H100 80G / H100 NVL 94G / H200 141G。
- **MODEL_PRESETS**：Llama-3.2 1B/3B、Llama-3.1 8B/70B、Llama-3.3 70B、Mistral-7B-v0.3、
  Mixtral-8x7B（MoE 示例）等，字段含 `params_b/hidden/layers/heads/kv_heads`。
  webbox 在此基础上扩充 Qwen2.5/3、DeepSeek、Gemma 系列（含 MoE 字段）。

## 5. 与 webbox 的映射

| 参考实现 | webbox `src/modules/vram/` |
|---|---|
| `GPU_SPECS` / `DTYPE_BYTES` / `MODEL_PRESETS` | `models.py` 中 `GPU_SPECS`、`DTYPE_BYTES`、`MODEL_PRESETS`（frozen dataclass） |
| `calculate_vram(...)` 训练/推理分支 | `service.py: VramService._estimate()` |
| `VRAMEstimate` | `models.py: VramEstimate`（`items: tuple[BreakdownItem]` 分解 + `fits/headroom`） |
| `fetch_model_config` | `service.py: fetch_model_config()`（httpx，可选网络） |
| `estimate_params_from_config` | `service.py: estimate_params()`（同公式） |
| Gradio UI | 不采用 → 三端前端各建 UI |

## 6. 注意事项

1. 参考实现 GB 用 **1024³**（GiB），与 vllm-vram-calc 的 10⁹（GB）不一致；
   webbox 统一用 1024³ 并在 UI 标注 GiB。
2. `attn_scores = b*h*s²` 项在长序列下主导训练激活显存——UI 提示"长序列训练显存暴涨"。
3. LoRA 公式按 7 个目标模块近似；参考实现自述"手动配置未充分测试"，webbox 以预设模型为主路径。
4. HF 拉取需网络且可能慢/失败 → 前端提供"手动参数"兜底，计算核心保持纯函数可离线测试。
