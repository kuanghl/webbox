# Refer: NiceGUI (refers/nicegui)

> 参考来源：`refers/nicegui/`（NiceGUI 完整源码，包位于 `refers/nicegui/nicegui/`）。
> 目标版本：**nicegui >= 3.16.0**（已安装 3.16.0）。本文档总结与 webbox 前端实现相关的接口、设计机制与用法。

## 1. 定位

NiceGUI 是基于 FastAPI + Vue 的 Python Web UI 框架：UI 用 Python 描述，浏览器端渲染。
对 webbox 是**主力 Web 前端**（已安装、API 已验证）。核心机制：
- `@ui.page` 路由装饰器；`ui.run()` 启动；
- 元素即对象，属性可直接赋值触发前端刷新（自动同步）；
- 后台任务用 `nicegui.run.io_bound / cpu_bound` 或原生 `asyncio`；
- `ui.timer` 定时刷新实现"轮询式响应"。

## 2. 应用入口

```python
from nicegui import ui

@ui.page('/')
def index():
    ui.label('hello')

ui.run(host='127.0.0.1', port=8080, title='WebBox', reload=False, show=False)
```

`ui.run` 位于 `nicegui/ui_run.py`。常用参数：`host/port/title/reload/show/storage_secret`。
`nicegui.run` 模块提供 `io_bound(fn, *args)`（线程池）、`cpu_bound(fn, *args)`（进程池）、
`thread_pool` / `process_pool`（`nicegui/run/__init__.py` 已验证存在）。

## 3. 3.16 已验证可用的核心元素

`ui.page, ui.run, ui.timer, ui.navigate, ui.upload, ui.linear_progress, ui.select, ui.input,
ui.button, ui.card, ui.label, ui.switch, ui.dialog, ui.notify, ui.dark_mode, ui.row, ui.column,
ui.separator, ui.badge, ui.slider, ui.number, ui.checkbox, ui.tabs, ui.tab, ui.tab_panels,
ui.tab_panel, ui.expansion, ui.image, ui.link, ui.markdown, ui.menu, ui.spinner, ui.toggle,
ui.scroll_area, ui.icon, ui.code, ui.table, ui.tree, ui.textarea, ui.date, ui.time,
ui.color_input, ui.html, ui.tooltip, ui.knob, ui.stepper, ui.avatar, ui.chip, ui.drawer,
ui.header, ui.footer, ui.left_drawer, ui.right_drawer, ui.grid, ui.scene, ui.plotly,
ui.aggrid, ui.json_editor, ui.log, ui.audio, ui.element, ui.context_menu, ui.notification, ui.download`

3.16 中**不存在**（勿用）：`ui.toast`（用 `ui.notify`）、`ui.password`（用 `ui.input(password=True)`）、
`ui.volume`、`ui.overlay`、`ui.map`、`ui.echarts`、`ui.rich_markdown`、`ui.iframe`。

### 3.1 导航（`ui.navigate`，已验证）

`ui.navigate.to(path)` / `back()` / `forward()` / **`reload()`** / `history`。
→ 语言切换策略：保存设置后 `ui.navigate.reload()` 整页重建，文案全部刷新，零额外代码。

### 3.2 主题（`ui.dark_mode`，已验证存在）

`ui.dark_mode` 是特殊元素（`ValueElement[bool | None]`，`nicegui/elements/dark_mode.py`）：

```python
ui.dark_mode.value = True    # 深色
ui.dark_mode.value = False   # 浅色
ui.dark_mode.value = None    # 跟随系统
```

赋值即时生效，无需重载。

### 3.3 定时器（响应式轮询的核心工具）

```python
timer = ui.timer(0.5, poll_state)   # 每 0.5s 调用；返回 False 或 .cancel() 停止
timer.active = False
```

webbox 翻译进度方案：后台协程消费 babeldoc 进度事件写入共享 `TaskState`，
UI 侧 `ui.timer(0.5, ...)` 读取并刷新 `ui.linear_progress.value` 与阶段标签。
（翻译协程运行在页面事件循环内，状态读写同线程，天然线程安全。）

### 3.4 上传 / 下载

```python
ui.upload(on_upload=handler, auto_upload=True, max_files=1)   # handler: UploadEventObjects
ui.download(file_path)                                        # 触发浏览器下载
```

### 3.5 通知 / 对话框

```python
ui.notify('Saved', type='positive')
with ui.dialog() as d, ui.card():
    ...
d.open()
```

## 4. 本项目页面结构

```
src/frontend/nicegui/
├── app.py            # create_app(ctx) 注册 @ui.page('/')；main() 组装 DI 后 ui.run
├── components.py     # 头部导航、语言/主题/用户切换器、进度卡片等复用组件
└── pages/
    ├── translate_page.py   # PDF 翻译（上传/参数/进度/结果）
    ├── vram_page.py        # 显存估算（表单/结果卡片/分解条）
    └── settings_page.py    # 主题/语言/用户/默认服务商设置
```

壳结构：`ui.header()`（标题 + 切换器）+ `ui.tabs`/`ui.tab_panels`（三个页面），
每页一个 `build(ctx)` 函数返回内容（组件化，见 AGENTS.md 3.4）。

## 5. 值得研读的 examples（`refers/nicegui/examples/`）

| 路径 | 学习点 |
|---|---|
| `menu_and_tabs/` | header + tabs 壳结构（本项目页面壳参照） |
| `modularization/` | 多文件拆分页面/组件的官方范式 |
| `progress/` | 进度条 + 后台任务 |
| `global_worker/` | 跨页面后台任务与状态共享 |
| `authentication/` | 用户态/会话管理 |
| `pytests/` | `nicegui.testing`（Screen/User fixture）测试范式 |
| `chat_app/` | 长任务 + 定时器刷新 UI 的完整例子 |

## 6. 测试与打包

- **测试**：`nicegui.testing.Screen` / `User` fixture（`nicegui/testing/`），
  `pytest` 下 `async def test_x(screen: Screen): await screen.open('/')`。
- **打包**：
  - `nicegui build`（需 esbuild/node）→ `dist/` 静态产物 + `nicegui run dist`；
  - 或 Docker（`examples/docker_image/`）；
  - 开发期直接 `python -m src.frontend.nicegui.app`。
  webbox 中 NiceGUI 作为可选依赖组 `nicegui` 安装，互不干扰。

## 7. 注意事项（gotchas）

1. 事件回调默认在事件循环线程执行；CPU 重活（PDF 解析）用 `run.cpu_bound` 或协程内 `run_in_executor`
   （babeldoc `async_translate` 内部已自行 `loop.run_in_executor`，直接 `await` 即可）。
2. `ui.timer` 回调里更新元素属性即可，不要手动 `page.update()`（NiceGUI 自动同步）。
3. 元素在页面上下文之外创建会报错——所有 UI 代码放在 `@ui.page` 函数内或其调用的 build 函数中。
4. `ui.select` 的 `value` 是选项字典的 key；`options` 传 `dict`（显示名→key）或 `list`。
5. 生产部署需 `storage_secret`（如用 `ui.storage`）；webbox 用文件持久化，不依赖它。
