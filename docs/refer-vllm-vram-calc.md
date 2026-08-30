# Refer: vllm-vram-calc (refers/vllm-vram-calc)

> 参考来源：`refers/vllm-vram-calc/`（Next.js 单页应用，核心逻辑在 `app/lib/calculations.ts`，
> 类型在 `app/lib/types.ts`）。**本项目 vram 模块 "Serving（vLLM 部署）" 模式的参照**。

## 1. 定位

针对 **vLLM 推理服务部署** 的显存规划器：给定 GPU（数量/显存/利用率）、模型结构、
量化与 vLLM 运行参数，计算 KV cache 容量、最大并发序列数、显存占用率，
并**生成可直接执行的 `vllm serve` 命令**。

## 2. 核心接口（`app/lib/`）

```ts
// types.ts
GPUConfig        { vram, numGpus, utilization }
ModelConfig      { weightsGB, numLayers, kvHeads, headDim, attnHeads, name?, maxContextLength? }
QuantizationConfig { method, bits, baseParams, groupSize }
VLLMConfig       { maxModelLen, maxNumSeqs, maxBatchedTokens, kvCacheDtype('auto'|'fp8'),
                   activationDtype, cudaGraphs, overheadPadding }
CalculationResult{ availableVramPerGpu, weightsPerGpu, cudaGraphsMemory, overheadMemory,
                   kvBytesPerToken, kvBytesPerSeq, totalKVCacheMemory, maxTokensForKV,
                   maxConcurrentSequences, totalBatchedTokens, freeMemory,
                   memoryUsagePercent, isOverCapacity, warnings[], command }

// calculations.ts
calculateVRAM(gpu, model, quant, vllm): CalculationResult   // 纯函数，无副作用
generateVLLMCommand({...}): string                          // 生成 vllm serve 命令
huggingface.ts  // HF config 拉取；storage.ts // localStorage 持久化
```

## 3. 计算公式（webbox Serving 模式移植基准）

> 注意：此项目用 **十进制 GB（10⁹ 字节）**，与 llm-vram-calc 的 1024³ 不同。
> webbox 统一 1024³（GiB），移植时换算。

```
available   = vram * numGpus * utilization
weights/gpu = weightsGB / numGpus                    # TP 切分
cuda_graphs = 2.5 GB（开启时，每卡）
kv_dtype_bytes = 1 if kvCacheDtype=='fp8' else 2
kv_heads/gpu = ceil(kvHeads / numGpus)               # TP 下 KV 头分摊
bytes/token  = 2 * kv_heads_per_gpu * headDim * kv_dtype_bytes * numLayers   # 2 = K+V
bytes/seq    = bytes/token * maxModelLen

kv_available = available - weights/gpu - cuda_graphs - overhead_padding
if kv_available <= 0 → isOverCapacity，warnings: 权重超显存

max_tokens_for_kv = floor(kv_available / bytes/token)
max_concurrent_seqs = min(floor(max_tokens_for_kv / maxModelLen), maxNumSeqs)
total_kv = max_concurrent_seqs * bytes/seq
usage_pct = (weights/gpu + cuda_graphs + overhead + total_kv) / available * 100
batched_tokens = min(maxBatchedTokens, max_concurrent_seqs * maxModelLen)
```

**警告规则**（UI 应保留）：
- 实际并发 < 请求并发 → 提示降低 max_model_len 或加显存；
- 占用率 > 95% → 提示降 batch/上下文；
- `kv_heads_per_gpu * numGpus > kvHeads` → TP 切分不整除的轻微不均衡提示。

**vLLM 命令生成**（`generateVLLMCommand`）：
`vllm serve <model> --tensor-parallel-size N --max-model-len L --max-num-seqs S
--max-num-batched-tokens T --gpu-memory-utilization U --dtype D [--kv-cache-dtype fp8]
[量化参数]`。

## 4. 与 webbox 的映射

| 参考实现 | webbox `src/modules/vram/` |
|---|---|
| `calculateVRAM` 主流程 | `service.py: VramService._estimate_serving()` |
| `GPUConfig/ModelConfig/VLLMConfig` | `models.py: VramRequest` 的 serving 字段（`num_gpus/max_model_len/max_num_seqs/gpu_memory_utilization/kv_cache_dtype`） |
| `CalculationResult.warnings/command` | `VramEstimate.notes` / `VramEstimate.vllm_command` |
| `kv_heads_per_gpu = ceil(kvHeads/numGpus)` | 同（TP 分摊） |
| Next.js UI | 不采用 → 三端前端 |

## 5. 注意事项

1. 该项目的 `weightsGB` 由用户在 UI 直接输入（或 HF 估算），webbox 则复用
   llm-vram-calc 的 `params_b × dtype_bytes` 统一计算权重，两参照互补。
2. `cuda_graphs=2.5GB` 是经验常数（vLLM 捕获 CUDA graph 的开销），保留为 UI 开关。
3. 十进制/二进制 GB 差异约 7.4%，跨参照对比数字时注意口径。
4. 纯函数设计（无 IO）值得照搬：webbox 的 `estimate()` 同样保持纯函数，
   HF 拉取单独成方法，便于单测。
