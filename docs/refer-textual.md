# Refer: Textual (refers/textual)

> 参考来源：`refers/textual/`（Textual 完整源码，包位于 `refers/textual/src/textual/`）。
> 目标版本：**textual >= 8.2.8**（源码版本即 8.2.8）。本文档总结与 webbox TUI 前端实现相关的接口、设计机制与用法。

## 1. 定位

Textual 是 Python 终端 UI（TUI）框架：`App` + `Screen` + `Widget` 组件树，
CSS（`.tcss`）布局，**reactive 属性**驱动 UI 刷新，`Worker` 跑后台任务。
webbox 的 TUI 前端采用它，与 NiceGUI/Flet 共享 `core` + `modules` 层。

## 2. 应用入口

```python
from textual.app import App, ComposeResult
from textual.screen import Screen

class WebboxApp(App):
    CSS_PATH = "styles.tcss"          # 相对 app 模块目录
    TITLE = "BabelDOC WebBox"
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with TabbedContent("Translate", "VRAM", "Settings"):
            ...

    def on_mount(self) -> None:
        self.push_screen(TranslateScreen())

WebboxApp(ctx).run()
```

`App.run()`（`src/textual/app.py:2308`）；测试用 `app.run_test()` 返回 `Pilot`。

## 3. 核心机制

### 3.1 Reactive 属性（响应式核心）

```python
from textual.reactive import reactive

class MyWidget(Widget):
    progress = reactive(0.0)                 # 变更自动触发 watch 与重绘

    @watch("progress")
    def _on_progress(self, value: float) -> None:
        self.query_one(ProgressBar).update(total=100, progress=value)
```

webbox 用法：`App.language` / `App.theme` 为 reactive；翻译进度用
`set_interval(0.5, poll)` 轮询共享 `TaskState`（与 Web 端同构）。

### 3.2 Workers（后台任务）

```python
self.run_worker(self._translate_coro(), exclusive=True, group="translate")
# 或同步函数：self.run_worker(blocking_fn, thread=True)
worker.cancel()
```

`Worker` 类见 `src/textual/worker.py`（`WorkerState`、`WorkerCancelled` 等）。
async worker 运行在 App 事件循环内 → 与 UI 同线程，共享状态读写安全。

### 3.3 主题（8.2 已验证）

- `App.theme: Reactive[str]`（`app.py:560`）——按**主题名**切换，内置主题
  `BUILTIN_THEMES`（`src/textual/theme.py:70`）：`textual-dark`、`textual-light`、
  `nord`、`gruvbox`、`catppuccin-mocha/latte/frappe/macchiato`、`dracula`、
  `tokyo-night`、`monokai`、`solarized-light/dark`、`rose-pine*`、`atom-one-*`、`ansi-dark`…
- 自定义主题：`Theme(name, primary, secondary, warning, error, success, accent,
  foreground, background, surface, panel, dark=...)` + `app.register_theme(theme)`。
- webbox 映射：设置 `dark` → `app.theme = "textual-dark"`，`light` → `"textual-light"`。

### 3.4 常用控件（本项目用到）

| 控件 | 用途 |
|---|---|
| `Header` / `Footer` | 顶/底栏（`textual.widgets`） |
| `TabbedContent` / `TabPane` | 标签页壳 |
| `Input` / `Select` / `Switch` / `Button` / `Slider` / `Checkbox` / `TextArea` | 表单 |
| `ProgressBar` / `Progress` | 进度（`ProgressBar(total=100).update(progress=x)`） |
| `Static` / `Label` / `RichLog` / `DataTable` | 文本/日志/表格 |
| `Card` / `Rule` / `Banner` | 布局与卡片 |
| `DirectoryTree` | 文件浏览（可选） |
| `Screen.push_screen / pop_screen` | 页面栈 |

`Select(options: Iterable[tuple[str, object]] | dict, value=...)`，`select.value` 取选中值。

### 3.5 消息与事件

控件事件 `on_input_changed`、`on_select_changed`、`on_button_pressed` 等；
跨组件通信用 `post_message` / `on_<Message>`。webbox 语言切换：
App 定义 `LanguageChanged` 消息，各 Screen `on_language_changed` 里刷新文案标签。

## 4. 本项目页面结构

```
src/frontend/textual/
├── app.py            # WebboxApp(App)：主题/语言 reactive、屏幕栈、bindings
├── styles.tcss       # 全局样式（颜色走主题变量 $primary 等）
├── screens/
│   ├── translate.py  # TranslateScreen：文件路径输入、参数、进度条、结果
│   ├── vram.py       # VramScreen：表单 + 结果 DataTable
│   └── settings.py   # SettingsScreen：主题/语言/用户/服务商
└── widgets/
    └── header.py     # HeaderBar：导航按钮 + 语言/主题/用户指示
```

TUI 无浏览器文件选择：翻译页用 `Input` 输入 PDF 路径（或 `DirectoryTree` 浏览），
结果直接打印输出路径。

## 5. 值得研读的 examples（`refers/textual/examples/`）

| 文件 | 学习点 |
|---|---|
| `calculator.py` / `calculator.tcss` | 表单 + 计算结果的最小完整 TUI（VRAM 页参照） |
| `sidebar.py` | 侧栏导航壳 |
| `json_tree.py` / `code_browser.py` | 树形/浏览类页面 |
| `theme_sandbox.py` | 主题切换与自定义主题 |
| `dictionary.py` | 输入联想/结果展示 |
| `mother.py` / `pride.py` | 动画与复杂布局 |

## 6. 测试与打包

- **测试**：`Pilot`（`src/textual/pilot.py:62`）：
  ```python
  async def test_smoke():
      async with WebboxApp(ctx).run_test() as pilot:
          await pilot.pause()
          assert app.query(TranslateScreen)
          await pilot.press("tab", "1")
  ```
  `pilot.click / press / pause / app` 驱动交互。
- **打包**：TUI 即 Python 脚本，推荐 `pyinstaller --onefile src/frontend/textual/app.py
  --add-data "styles.tcss:."`（CSS 需随包）；或 `shiv`/`pex` 单文件 zipapp。
  webbox 中文本前端作为可选依赖组 `textual` 安装。

## 7. 注意事项（gotchas）

1. `CSS_PATH` 相对 **app 模块所在目录**解析；打包时务必 `--add-data` 带上 `.tcss`。
2. `Select.value` 初始值必须在 options 中，否则报错；options 变更用 `select.options = ...`。
3. `ProgressBar` 必须先 `mount` 再 `update`；`total` 未知时用 `bar()` 不确定模式。
4. worker 里不要直接改 widget 属性以外的 UI 结构（异步 worker 同线程可以，
   线程 worker 必须经消息/`call_from_thread`）。
5. 终端配色受用户终端影响，样式里用主题变量（`$primary`、`$surface`）而非硬编码色值。
