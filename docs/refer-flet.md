# Refer: Flet (refers/flet)

> 参考来源：`refers/flet/`（Flet SDK 完整源码，Python 包位于 `sdk/python/packages/flet/src/flet/`）。
> 目标版本：**flet 0.86.5**（`frontend.md` 要求）。本文档总结与 webbox 前端实现相关的接口、设计机制与用法。

## 1. 定位

Flet 是 Flutter 驱动的跨平台 UI 框架：同一套 Python 代码可构建 Web / 桌面 / 移动端应用。
0.86.x 引入了**声明式 + 响应式**新 API（`@ft.component` / `@ft.observable` / `page.render`），
是本项目 Flet 前端应遵循的设计机制（经典 `page.add` + `page.update` 模式仍可用，作为回退）。

## 2. 应用入口

```python
import flet as ft

def main(page: ft.Page):
    page.title = "WebBox"
    page.render(App)          # 新 API：渲染声明式组件树

ft.run(main, host="127.0.0.1", port=8550, view=ft.AppView.WEB_BROWSER)
```

`ft.run(main, ...)` 关键参数（`src/flet/app.py`）：

| 参数 | 说明 |
|---|---|
| `main` | 入口函数，签名 `(page: ft.Page) -> None`，可为协程 |
| `host` / `port` | Web 服务绑定地址（port=0 自动选择） |
| `view` | `AppView.WEB_BROWSER`（起 web 服务并打开浏览器）/ `FLET_APP`（桌面窗口）/ `FLET_APP_HIDDEN` / `NATIVE` |
| `assets_dir` / `upload_dir` | 静态资源与上传目录 |
| `no_cdn` | 离线模式（不加载 CanvasKit/Pyodide/字体 CDN） |
| `export_asgi_app` | 返回 FastAPI ASGI app 而不启动事件循环（便于测试/嵌入） |

多页面路由用 `page.render_views(ViewClass)`（见 `examples/apps/declarative/routing_two_pages`）；
单页应用用 `page.render(Component)`，配合内容切换实现多"页"。

## 3. 声明式 + 响应式 API（0.86 新机制，本项目采用）

### 3.1 `@ft.component` — 声明式组件

组件就是返回控件树的普通函数，可带参数（`src/flet/components/component_decorator.py`）：

```python
@ft.component
def Header():
    return ft.Row([ft.Text("Todos", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM)],
                  alignment=ft.MainAxisAlignment.CENTER)

@ft.component
def Footer(active_tasks_number: int, clear_completed):
    return ft.Row([ft.Text(f"{active_tasks_number} items left"),
                   ft.OutlinedButton("Clear completed", on_click=clear_completed)],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
```

### 3.2 `@ft.observable` — 响应式状态

`@ft.observable` 装饰 `@dataclass`，字段变更自动触发 UI 刷新（无需手动 `page.update()`）：

```python
@ft.observable
@dataclass
class TodoAppState:
    tasks: list[TaskItem] = field(default_factory=list)
    status: str = "all"

    def status_changed(self, e: ft.Event[ft.Tabs]):
        self.status = self.statuses[e.control.selected_index]

    def on_task_status_changed(self):
        cast(ft.Observable, self).notify()   # 手动失效（嵌套对象变更时）
```

要点：
- 事件处理器签名 `(e: ft.Event[T])`，`e.control` 访问触发控件；
- 嵌套对象/列表内部变更需 `cast(ft.Observable, state).notify()`；
- 经典模式（`page.update()`）下需 `ft.context.disable_auto_update()`，新 API 默认自动更新。

### 3.3 渲染

```python
if __name__ == "__main__":
    ft.run(lambda page: page.render(TodoAppView))   # 单视图
    # ft.run(lambda page: page.render_views(MyViews))  # 多视图路由
```

## 4. 本项目会用到的核心控件

| 控件 | 用途 |
|---|---|
| `ft.Page` | 页面根：`page.title`、`page.theme_mode`、`page.add/render`、`page.update()`、`page.run_task(coro)`（跑协程） |
| `ft.NavigationRail` / `ft.NavigationRailDestination` | 侧边导航（`src/flet/controls/material/navigation_rail.py`） |
| `ft.Tabs` / `ft.Tab` | 标签页 |
| `ft.TextField` / `ft.Dropdown` / `ft.Switch` / `ft.Slider` / `ft.Checkbox` | 表单输入 |
| `ft.FilePicker` | 文件选择（`page.overlay.append(fp); page.file_picker.result` 事件） |
| `ft.ProgressBar` / `ft.LinearProgressIndicator` | 进度条 |
| `ft.ElevatedButton` / `ft.OutlinedButton` / `ft.IconButton` | 按钮 |
| `ft.Card` / `ft.Container` / `ft.Row` / `ft.Column` / `ft.SafeArea` | 布局 |
| `ft.DataTable` / `ft.DataRow` / `ft.DataCell` | 结果表格 |
| `ft.FloatingActionButton` / `ft.SnackBar` | 操作与轻提示 |
| `ft.Colors` / `ft.Icons` | 主题色与图标枚举 |

## 5. 主题 / 国际化 / 用户切换

- **主题**：`page.theme_mode = ft.ThemeMode.DARK | LIGHT | SYSTEM`；
  自定义主题 `page.theme = ft.Theme(color_scheme_seed=..., visual_density=...)`。
- **i18n**：Flet 无内建 i18n，文案来自 webbox 的 `src/core/i18n.py`（`tr(key)`）；
  语言切换后重建内容并 `page.update()`（或依赖 observable 自动刷新）。
- **用户/配置持久化**：Flet 提供 `page.session` 与本地存储能力，但 webbox 统一走
  `src/core/store.py`（JSON 文件），三端一致。

## 6. 值得研读的 examples（`refers/flet/sdk/python/examples/`）

| 路径 | 学习点 |
|---|---|
| `apps/declarative/minimal_reactive/` | `@ft.component` + `page.render` 最小示例 |
| `apps/declarative/todo/` | **完整 observable 状态 + 组件拆分范式**（本项目主要参照） |
| `apps/declarative/navigation_drawer/` | 导航壳 + 多视图切换 |
| `apps/declarative/routing_two_pages/` | `render_views` 路由 |
| `apps/declarative/timer/` | observable 内跑 asyncio 循环（进度轮询参照） |
| `apps/counter/editable/` | 经典 `page.update()` 模式 |
| `apps/authentication/` | 登录/用户态管理 |

## 7. 测试与打包

- **测试**：`src/flet/testing/`（`FletTestApp` + pytest 插件 `src/flet/pytest_plugin.py`），
  用法见 `examples/apps/flet_test_counter/`。
- **打包**：`flet build web`（Web，纯 Python 分发）；`flet build linux/windows/macos/ios/android`
  （桌面/移动，需 Flutter SDK）。`examples/apps/flet_build_test/` 有构建示例。
  webbox 中 Flet 前端作为可选依赖组 `flet` 安装，`python -m src.frontend.flet.app` 启动。

## 8. 注意事项（gotchas）

1. `ft.run` 内部 `asyncio.run`，入口协程里才能 `await`；后台任务用 `page.run_task`。
2. observable 的**列表/字典内部变更**不会自动通知，需 `notify()` 或整体替换字段。
3. 事件回调默认在 UI 线程执行，重活（翻译）放 `page.run_task` 协程 + 轮询状态。
4. `FilePicker` 必须先 `page.overlay.append(file_picker)` 才能 `pick_files()`。
5. Web 模式下 `upload_dir` 决定上传落盘位置；`no_cdn=True` 用于内网部署。
