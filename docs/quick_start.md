# 快速开始

## 1. 环境准备

要求 Python >= 3.12，推荐用 [uv](https://docs.astral.sh/uv/) 管理虚拟环境：

```sh
cd webbox
uv venv .venv
uv pip install -e ".[test]"          # 核心依赖 + NiceGUI 前端 + pytest
# 可选前端：
uv pip install -e ".[textual]"       # Textual 终端 TUI
uv pip install -e ".[flet]"          # Flet（尚未实现）
```

核心依赖包含 `nicegui`、`babeldoc`、`pydantic-settings`、`httpx`。

## 2. 启动 NiceGUI 前端

```sh
.venv/bin/python -m src.frontend.nicegui.app
# 或安装后使用入口点：
webbox-nicegui
```

启动后浏览器访问 `http://127.0.0.1:8080`。单页面三个标签页：

- **Translate**：上传 PDF，选择源/目标语言、AI 服务商（OpenAI / DeepSeek /
  智谱 GLM / Claude / Ollama 等）、模型与 API Key，开始翻译并实时查看进度，
  可取消、可下载翻译结果（mono / dual PDF）。
- **VRAM Calculator**：估算 LLM 推理 / 训练（全参 / LoRA）/ 部署（vLLM 等）
  所需显存，支持模型预设或手动填参、多 GPU 张量并行提示。
- **Settings**：默认服务商 / 模型 / Base URL / API Key、界面语言、主题、
  当前用户（模拟多用户），设置按用户持久化到 `./data/`。

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEBBOX_HOST` | `127.0.0.1` | 监听地址 |
| `WEBBOX_PORT` | `8080` | 监听端口 |
| `WEBBOX_LOG_LEVEL` | `INFO` | 日志级别 |
| `WEBBOX_DATA_DIR` | `./data` | 用户设置持久化目录 |
| `WEBBOX_LOG_DIR` | `./logs` | 日志目录（按天滚动，保留 30 天） |

示例：`WEBBOX_PORT=8099 .venv/bin/python -m src.frontend.nicegui.app`

## 2.1 启动 Textual TUI

```sh
.venv/bin/python -m src.frontend.textual.app
# 或安装后使用入口点：
webbox-tui
```

终端内运行，功能与 NiceGUI 版一致：Translate（进度/取消/结果）、
VRAM Calculator（推理/训练/vLLM 部署）、Settings（语言/主题/用户/服务商默认值）。

## 3. 运行测试

```sh
.venv/bin/python -m pytest tests -q
```

- `tests/unit/`：VRAM 估算、翻译服务（mock babeldoc 管道）、core 配置/国际化/设置存储。
- `tests/frontend/`：NiceGUI 页面冒烟测试（in-process `user_simulation`，无需浏览器）
  与 Textual TUI 冒烟测试（headless `App.run_test`）。

## 4. 项目结构

```
src/
├── core/            # 配置、常量、i18n、主题、设置存储、AppContext
├── modules/
│   ├── translate/   # 翻译引擎接口 + babeldoc 服务实现
│   └── vram/        # 显存估算接口 + 服务实现
└── frontend/
    ├── nicegui/     # NiceGUI 单页面应用（app.py + pages/ + components.py）
    └── textual/     # Textual 终端 TUI（app.py + pages/）
tests/
├── unit/
└── frontend/
```

前端只通过 `core` 与 `modules` 的接口层通信，不直接依赖具体实现。