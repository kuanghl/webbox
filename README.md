# webbox

## 1. overview

webbox是一个多功能工具箱，支持功能如下：

- BabelDOC接入多种 AI 服务商（OpenAI、DeepSeek、智谱 GLM、Claude、Ollama 等），实时显示进度输出高质量翻译文档
- llm本地部署参数及显存等资源测算，支持多种芯片平台及多种模型
- 支持本地模型接入，provider
- 支持主题切换，支持语言切换，用户切换，用户设置记录保存等

## 2. quick-start

完整说明见 [docs/quick_start.md](docs/quick_start.md)。

```sh
uv venv .venv
uv pip install -e ".[test,textual]"
.venv/bin/python -m src.frontend.nicegui.app   # 访问 http://127.0.0.1:8080
.venv/bin/python -m src.frontend.textual.app   # 终端 TUI（或 webbox-tui）
.venv/bin/python -m pytest tests -q            # 运行测试
```