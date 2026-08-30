# Refer: llm-gpu-vram-calculator (refers/llm-gpu-vram-calculator)

> 参考来源：`refers/llm-gpu-vram-calculator/`（Vite + TypeScript Web 应用，MIT）。
> 面向 **LLM serving 显存 / KV cache 压力 / 粗略吞吐** 的交互式计算器。
> 本项目借鉴其**数据目录设计（带来源链接的模型/GPU 目录）**、**吞吐估算公式**与
> **calculator-framework 的 manifest/adapter 分层思想**。

## 1. 定位

与 vllm-vram-calc 同域（serving 显存规划），但更"产品化"：
- 引导式设置 + 详细参数面板；
- **带官方来源链接**的模型目录（Qwen3/3.5/3.6、DeepSeek V3/R1/V4、Gemma 3/4）与 GPU 目录
  （含发布年份、厂商、架构、规格来源 URL）；
- 量化/KV cache 支持提示（FP16/FP8/INT8/INT4/FP32 回退）；
- **公式/理论面板**（展示每条估算的公式与假设）；
- CSV 导出（模型目录、硬件目录、当前估算指标）；
- `en_US` / `zh_CN` 完整 i18n（含公式与理论说明）——与 webbox 的 i18n 需求一致。

## 2. 核心接口（`src/`）

```ts
// utils/formulas.ts
weightBytesByQuant: Record<RuntimeQuantType, number>     // 每参数字节数（按量化）
kvBytesByQuant: Record<KvQuantType, number>              // KV cache 每元素字节数
estimateModelWeightGB(paramsB, quant, awqGroup=32): number
computeKvCacheVramGB(...): number                        // KV cache 显存
estimatePromptTokensPerSecond(fp16Tflops, totalParamsB, gpuCount): number
    // prefill 吞吐 ≈ 算力上限: tokens/s ≈ fp16Tflops*1e12 / (2 * params*1e9) / gpuCount 量级
estimateGenerationTokensPerSecond(...): number
    // decode 吞吐 ≈ 带宽上限: tokens/s ≈ bandwidth / (params_bytes * 激活比例)
```

```
// data/modelDefs.ts  ModelDef: 参数/上下文/发布日期/来源链接（model card + 技术报告）
// data/gpuCards.ts   GPUCard: 显存/带宽/发布年份/厂商/架构/规格来源 URL
// calculator-framework/
//   manifest.schema.json      # 计算器可移植声明 schema（输入/输出/公式声明）
//   docs/adapter-contract.md  # 基础 UI 壳 与 领域逻辑 的运行时边界
//   docs/semantic-merge.md    # 跨项目找公共部分的方法
//   examples/llm-gpu-vram.manifest.json
```

## 3. 值得借鉴的设计机制

1. **数据与计算分离 + 来源可溯**：模型/GPU 目录是纯数据文件，每条带 `label/url/note`
   来源。webbox 的 `MODEL_PRESETS`/`GPU_SPECS` 采用同构设计（`ModelSpec.source` 可选字段），
   UI 可展示"参数来源"增强可信度。
2. **公式透明**：结果页展示公式与假设（"weights = params × bytes/param"），
   webbox VRAM 结果区加"计算说明"折叠面板。
3. **吞吐双上限模型**：prefill 受**算力（TFLOPS）**限制、decode 受**带宽（GB/s）**限制——
   这是 llm-vram-calc 没有的维度，webbox 在 serving 结果中补充"粗估吞吐"
   （`prompt_tps ≈ tflops*1e12 / (2*params*1e9)`、`gen_tps ≈ bandwidth*1e9 / (active_params_bytes)`）。
4. **manifest/adapter 分层**（calculator-framework）：UI 壳只认 manifest 声明的输入输出，
   领域公式走 adapter——对应 webbox 的 `modules/vram/interfaces.py`（`VramCalculator` ABC）
   + 前端只依赖接口的架构（AGENTS.md 3.4）。其"证据阶梯"原则（1 个实例只记录模式、
   3 个实例才抽公共框架）与 ponytail 的 YAGNI 一致，值得在模块扩展时遵循。
5. **i18n 覆盖公式文案**：连理论说明都双语——webbox i18n 键值表需包含 VRAM 分解项名称。

## 4. 与 webbox 的映射

| 参考实现 | webbox |
|---|---|
| `estimatePromptTokensPerSecond` / `estimateGenerationTokensPerSecond` | `VramService._estimate_serving()` 的 `prompt_tps/gen_tps` 字段（GPU 需补 `tflops_fp16` 数据） |
| `modelDefs.ts` 来源链接 | `ModelSpec.source: str \| None` |
| 公式面板 | 三端 VRAM 页"计算说明"折叠区（i18n 键 `vram.formula.*`） |
| CSV 导出 | 暂不做（YAGNI）；如需要，`VramEstimate` 序列化即可 |
| Vite/TS 应用壳 | 不采用 → 三端 Python 前端 |

## 5. 注意事项

1. 吞吐公式是**理论上限**（未计 kernel 效率/调度开销），UI 必须标注"粗估"。
2. 其 GPU 目录含 FP16 TFLOPS 数据（dense Tensor Core 口径）——webbox 移植 `GPU_SPECS`
   时补充 `tflops_fp16` 字段用于吞吐估算。
3. MoE 模型 decode 带宽上限应按**激活参数**（active_params_b）而非总参数计算，
   与 llm-vram-calc 的 MoE 处理一致。
4. 该项目为 TS 实现，无 Python 代码可直接复用，仅借鉴数据结构与公式。
