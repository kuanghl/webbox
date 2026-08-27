# BabelDOC WebUI（webbox）改造计划

> 状态：待实施 · 参考基线：`nicegui/examples`（官方示例）+ 同仓库 `deploy/` 项目已落地的改造模式
>
> 目标（按优先级）：**可阅读性**（单一文件巨石 → 分层模块化）、**可拓展性**（引擎/服务商/页面可插拔，测试兜底）、**性能**（事件循环去阻塞、模型加载缓存、大文件流式处理、UI 增量更新）。

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [现状分析（问题清单）](#2-现状分析问题清单)
3. [参考模式映射表](#3-参考模式映射表)
4. [目标架构](#4-目标架构)
5. [逐步改造计划（P0–P6）](#5-逐步改造计划)
6. [实施顺序与依赖](#6-实施顺序与依赖)
7. [验证策略](#7-验证策略)
8. [风险与缓解](#8-风险与缓解)
9. [附录：关键代码位置索引](#9-附录关键代码位置索引)

---

## 1. 背景与目标

webbox 是基于 [NiceGUI](https://nicegui.io/) 构建的 BabelDOC PDF 翻译 Web 界面。当前代码
功能完整（多服务商模型管理、翻译任务执行、进度展示、历史记录、babeldoc 补丁层、TOC 后处理），
但存在三个结构性问题：

| 维度 | 现状 | 改造目标 |
|------|------|----------|
| 可阅读性 | `ui/app.py` 单文件 1950 行，UI 骨架、业务逻辑、翻译管线组装、CSS 全部混在一起 | 分层（视图 / 业务 / 领域）+ 按职责拆模块，单文件 ≤ 400 行 |
| 可拓展性 | 翻译引擎硬编码 babeldoc；无引擎抽象、无 REST API、无测试 | core 领域层不依赖 NiceGUI，可单测；引擎可插拔；`APIRouter` 预留 API |
| 性能 | `DocLayoutModel.load_onnx()` 每次翻译重新加载且阻塞事件循环；上传整文件读入内存；UI 全量重建 | 阻塞工作移出事件循环；进程级模型缓存；`FileUpload.save()` 分块落盘；事件驱动增量更新 |

**改造总原则（行为等价优先）：**

1. 每个改造项独立提交，除「显式行为变更清单」（见 §5 各条标注）外，用户可感知行为不变。
2. 领域层（`core/`）禁止 `import nicegui`；UI 层不直接操作 babeldoc。
3. 后台任务（翻译 Job）是唯一的并发单元；UI 与业务之间只通过**事件订阅**通信
   （借鉴 `nicegui/examples/threaded_nicegui` 的 `Event` 发布/订阅 与同仓库 `deploy/ui/events.py` 的 `EventBus`）。
4. 每个阶段结束必须通过：单元测试 + 手工冒烟（见 §7）。

---

## 2. 现状分析（问题清单）

| # | 位置 | 问题 | 类别 |
|---|------|------|------|
| P-01 | `ui/app.py`（1950 行） | 巨石文件：翻译器注册表、PageState、页面骨架、上传/选项/进度/结果/历史/设置对话框、`run_translation` 300 行管线组装、内联 CSS，全部在一个模块 | 可阅读性 |
| P-02 | `ui/app.py:24-95` | 全局可变状态 + 手工 `threading.Lock`（`_active_translators` / `_active_pages`），并用 `_safe_call` 吞掉「元素所属客户端已删除」的 RuntimeError——本质是「后台任务直接触碰 UI 元素」的设计缺陷 | 可阅读性 / 稳定性 |
| P-03 | `ui/app.py:1368-1668` | `run_translation` 单函数承担：模型配置解析 → 创建 2 个 translator → 设置限流器 → 加载 onnx 布局模型 → 读术语表 → 逐文件构造 `TranslationConfig` → 消费 `async_translate` 事件流 → TOC 后处理 → 写历史 → 刷 UI，职责严重过载 | 可阅读性 / 可拓展性 |
| P-04 | `ui/app.py:1468-1476` | `DocLayoutModel.load_onnx()` 在**每次**翻译时重新加载（重 CPU/IO，秒级），且同步执行在事件循环内阻塞整个进程（影响其他在线客户端） | 性能 |
| P-05 | `ui/app.py:1368-1370` | `import babeldoc...`、`fitz`（`toc_generator`）等重导入发生在事件循环线程，多客户端并发时放大阻塞 | 性能 |
| P-06 | `ui/app.py:991-1007` | 上传用 `await e.file.read()` 将**整个 PDF 读入内存**再写出；临时目录 `tmp/babeldoc-webui/` 全局共享，同名文件互相覆盖（多客户端并发上传同名 PDF 是真实风险）。NiceGUI 3.x 的 `FileUpload` 已提供 `save()`（内部 1MB 分块异步写，大文件自动 spool 到磁盘，见 `nicegui/elements/upload_files.py`） | 性能 / 稳定性 |
| P-07 | `ui/components/settings.py:614-623` | `SettingsManager.save()` 直接 `open(w)` 整文件写，非原子（进程崩溃/断电可能损坏 `settings.json`）；同仓库 `history.py:43-50` 已是 tmp+`replace` 原子写，两者不一致 | 稳定性 |
| P-08 | `ui/components/settings.py:12-240, 627-684` | `BUILTIN_PROVIDERS` 为大 list[dict] 且 `get_builtin_provider_by_id` 线性查找；`get_selected_model_config` 等每次 O(服务商×模型) 遍历；数据与持久化逻辑、UI 辅助（`get_all_model_options` 返回前端 label）混在同一模块 | 可阅读性 / 性能(轻微) |
| P-09 | `ui/components/babeldoc_compat.py`（926 行） | 单一 monkeypatch 模块混合 4 个独立关注点：P1 段落重分行、P2a 术语过滤、P2b 容错 JSON 解析、P3 批量部分匹配补翻、P4 占位符阈值；新增/回退单个补丁困难 | 可阅读性 / 可拓展性 |
| P-10 | `ui/app.py:1573-1585` | 进度更新为「事件 → 直接调 `ps.progress_bar.set_value()`」（外包 `_safe_call`），而非 NiceGUI 惯用的 binding / 事件订阅（`global_worker` 示例的 `bind_value_from(worker, 'progress')`）；后台任务与 UI 生命周期未解耦 | 可阅读性 / 性能(无节流) |
| P-11 | `ui/app.py:1677-1724, 1010-1041` | 结果列表 / 文件列表每次变更 `clear()` + 全量重建 DOM；文件多时浪费且闪烁 | 性能 |
| P-12 | 全项目 | 无单元测试、无 UI 测试、无静态检查（ruff/mypy）、大量函数无类型注解 | 可拓展性 |
| P-13 | `ui/app.py:1736-1830+` | 大段 CSS 通过 `ui.add_head_html` 在**每个客户端**连接时重复注入；应改为静态 CSS 文件 + 启动期一次性 `shared=True` 注入（参考 `deploy/ui/layout.py:95`） | 性能(轻微) / 可阅读性 |
| P-14 | 架构 | 无引擎抽象（写死 babeldoc）；无 REST API（无法脚本化/无头调用）；`pyproject.toml` `package=true` 但 `packages=[]`，`ui/` 未纳入打包 | 可拓展性 |
| P-15 | `main.py:15-21` vs `README.md` | 入口默认端口 8765，help 文案写 8080，README 写 8080——三处不一致 | 可阅读性 |

**结论：** P-01/02/03/09/10 是结构性问题，必须按「先抽领域层 → 再建任务模型 → 最后拆 UI」
的顺序改造；P-04/05/06/07/08/11/13 是可在对应改造项中顺手解决的点状问题；P-12 贯穿始终。

---

## 3. 参考模式映射表

> 本改造「抄作业」的对象。示例路径均相对 `llms-deploy/nicegui/examples/`。

| 模式 | 来源示例（关键文件） | 在 webbox 的应用点 |
|------|---------------------|--------------------|
| **模块化页面**：页面拆到独立模块，`@ui.page` 路由化；`theme.frame()` contextmanager 统一骨架；`APIRouter` 挂子路由 | `modularization/main.py`、`modularization/theme.py`、`modularization/api_router_example.py` | P3.1–P3.4：`ui/layout.py` 的 `page_frame`、`ui/pages/home_page.py`、设置/历史拆分、`/api` 预留 |
| **Worker + 后台任务**：`Worker` 类持有 `progress/is_running` 属性，`app.on_startup` 初始化资源，`background_tasks.create(...)` 启动，UI 用 `bind_value_from(worker, 'progress')` 纯绑定驱动 | `global_worker/main.py` | P2.1、P3.5：`JobManager` + `TranslationJob`，进度条绑定驱动，移除 `_safe_call` |
| **事件发布/订阅解耦**：业务侧 `Event.emit()`，UI 侧 `subscribe`；后台逻辑与 UI 生命周期彻底分离 | `threaded_nicegui/main.py`；同仓库 `deploy/ui/events.py`（EventBus：线程安全 publish/subscribe、revision、history 补差） | P2.3：Job 事件 → 页面订阅（client 断开自动退订）；可选升级 `EventBus` 支持 SSE |
| **CPU 密集移出主循环**：`run.cpu_bound(func, queue)` + `Manager().Queue` 传进度 + `ui.timer` 拉取 | `progress/main.py` | P2.2：onnx 模型加载 / babeldoc 重活经 `run.cpu_bound`；进度经 Job 属性 + 绑定回传 |
| **IO 密集移出主循环**：`await run.io_bound(api_call, ...)`；按钮 `props('loading')` | `ai_interface/main.py` | P2.2：模型连通性测试、术语表读取等 |
| **任务取消**：`asyncio.create_task` + 新请求到来时 `task.cancel()` | `search_as_you_type/main.py` | P2.6：取消语义统一到 `Job.cancel_event`；模型测试等一次性请求取消 |
| **用户态持久化**：`ui.run(storage_secret=...)` + `app.storage.user/browser` | `single_page_app/main.py`；同仓库 `deploy/ui/app.py:120` | P4.3（可选）：主题等 UI 偏好；不替代 settings.json |
| **UI 测试**：`pytest_plugins = ["nicegui.testing.plugin"]`，`User` fixture `user.open('/') / should_see / find().click()` | `pytests/app/startup.py`、`pytests/tests/test_with_user.py`；同仓库 `deploy/tests/conftest.py`（`isolated_data` 数据隔离 + `ui_user` 路由重注册） | P0.2、P5.2：测试骨架与 UI 测试 |
| **文件下载**：`ui.download(path)` | `generate_pdf/main.py` | 保持现状（P3.6 增量刷新时保留） |
| **静态文件/样式**：`app.add_static_files` + `<link>` 引用 | 同仓库 `deploy/ui-static/main.css` 先例；`modularization/theme.py` | P3.1：CSS 静态化 |
| **REST API**：`APIRouter(prefix=...)` + `@router.get/post` 与页面并存 | `modularization/api_router_example.py`；`fastapi/main.py` | P6.2：`/api/jobs` 无头接口 |
| **可选持久化后端**：Redis / SQLite 存储抽象 | `redis_storage/`、`sqlite_database/` | 多实例部署时再评估（当前单进程） |
| **容器化** | `docker_image/`、`ros2/`（多容器 compose） | P6.4（可选） |

> 同仓库 `deploy/` 项目已经完整实践了 `EventBus`、`page_frame` 布局、`i18n`、
> `logging_setup`（滚动日志文件）、`conftest` 数据隔离等模式。**webbox 的改造在遵循
> `nicegui/examples` 官方模式的同时，尽量与 `deploy/` 保持一致的目录习惯与命名**，
> 使仓库内两个 Web 项目风格统一。


---

## 4. 目标架构

### 4.1 分层

```
┌────────────────────────────────────────────────────────────┐
│ main.py          入口：argparse / logging / mp start method │
├────────────────────────────────────────────────────────────┤
│ ui/  视图层（唯一允许 import nicegui 的包）                  │
│   app.py         组装：注册路由 / 启动 hook / ui.run        │
│   layout.py      page_frame + 主题 + 静态 CSS（frame 模式） │
│   pages/         home_page.py（/）等，每页一个模块           │
│   components/    sections/*（页面分区）、settings/*（设置 Tab）│
├────────────────────────────────────────────────────────────┤
│ core/  领域层（禁止 import nicegui，可独立单测）             │
│   providers.py   内置服务商预设 + 索引                       │
│   models.py      Settings 系 dataclass（纯数据）            │
│   settings_store.py / history_store.py   持久化（原子写）    │
│   jobs/          translation_job.py / job_manager.py       │
│   engine/        引擎抽象 + babeldoc 适配器 + 工厂 + 缓存    │
│   pipeline/      babeldoc monkeypatch（按关注点拆分）        │
│   postprocess/   toc.py 等后处理                            │
├────────────────────────────────────────────────────────────┤
│ babeldoc / fitz / onnx …  第三方（仅 core/engine 触碰）      │
└────────────────────────────────────────────────────────────┘
```

### 4.2 目标目录结构

```
webbox/
├── main.py                          # 入口（保持 40 行内）
├── pyproject.toml                   # 修正打包配置 + dev 依赖 + ruff/mypy 配置
├── assets/
│   └── static/main.css              # 从 app.py 内联 CSS 迁出
├── core/                            # 领域层（无 NiceGUI 依赖）
│   ├── __init__.py
│   ├── providers.py                 # BUILTIN_PROVIDERS + id 索引
│   ├── models.py                    # ModelConfig/Provider/Settings 系 dataclass
│   ├── settings_store.py            # SettingsManager（原子写、schema 迁移）
│   ├── history_store.py             # HistoryManager
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── translation_job.py       # Job 状态机 + 类型化事件（dataclass）
│   │   └── job_manager.py           # 全局注册表 + shutdown 取消
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── base.py                  # TranslateEngine 协议 + JobEvent 类型
│   │   ├── babeldoc_engine.py       # babeldoc 适配器（消费 async_translate）
│   │   ├── translator_factory.py    # ModelConfig → OpenAITranslator
│   │   ├── config_builder.py        # Settings+files → TranslationConfig
│   │   └── layout_model.py          # DocLayoutModel 进程级缓存
│   ├── pipeline/
│   │   ├── __init__.py              # apply_patches() 统一入口
│   │   ├── paragraph_fix.py         # P1 段落重分行补丁
│   │   ├── glossary_filter.py       # P2a 术语过滤 + P2b 容错 JSON
│   │   ├── partial_match.py         # P3 批量部分匹配补翻
│   │   └── placeholder_limit.py     # P4 占位符阈值
│   └── postprocess/
│       ├── __init__.py
│       └── toc.py                   # 原 toc_generator.py
├── ui/
│   ├── __init__.py
│   ├── app.py                       # create_app()/run()：路由注册 + startup/shutdown hook
│   ├── layout.py                    # page_frame(title) + 主题 + CSS 注入（一次）
│   ├── pages/
│   │   ├── __init__.py
│   │   └── home_page.py             # 主页面 content()
│   └── components/
│       ├── __init__.py
│       ├── page_state.py            # PageState（UI 侧状态）
│       ├── sections/
│       │   ├── __init__.py
│       │   ├── upload_section.py
│       │   ├── options_section.py
│       │   ├── progress_section.py
│       │   ├── results_section.py
│       │   └── history_section.py
│       └── settings/
│           ├── __init__.py          # open_settings_dialog()
│           ├── dialog.py
│           ├── providers_tab.py
│           ├── translation_tab.py
│           ├── pdf_tab.py
│           ├── doc_processing_tab.py
│           ├── rpc_tab.py
│           └── paths_tab.py
└── tests/
    ├── conftest.py                  # isolated_data + ui_user（对齐 deploy/tests 模式）
    ├── test_settings_store.py
    ├── test_history_store.py
    ├── test_providers.py
    ├── test_config_builder.py
    ├── test_toc_parser.py
    ├── test_pipeline_patches.py
    ├── test_jobs.py                 # FakeEngine 驱动的 Job 流程
    └── test_ui_home.py              # User fixture 冒烟
```


> 迁移期兼容：`ui/components/settings.py`、`history.py`、`toc_generator.py`、
> `babeldoc_compat.py` 保留为**薄 re-export shim**（几行 `from core... import ...`），
> 保证旧导入路径不炸；P5 完成并稳定一个版本后删除。

### 4.3 核心运行时模型

- **TranslationJob**（`core/jobs/`）：一次「点击开始翻译」= 一个 Job，拥有
  `id / files / status / progress / stage / results / error / cancel_event / translator 句柄`。
  Job 自己创建并关闭 translator（`finally`），不再需要全局 `_active_translators`。
- **JobManager**：进程级单例。`submit(files, settings_snapshot, on_event) -> job`；
  `app.on_shutdown` 时取消全部 running job（替代 `_cancel_running_tasks`）。
- **事件流**：引擎产出类型化 `JobEvent`（`ProgressUpdate / StageChanged / FileFinished /
  Error / Finished`，dataclass 而非裸 dict），Job 转发给订阅者；UI 页面在 client
  连接时订阅、`client.on_disconnect` 退订——彻底取代 `_safe_call`。
- **阻塞工作**：onnx 加载、babeldoc 重导入、同步解析等经 `run.cpu_bound` /
  `run.io_bound`（layout model 进程级缓存后，加载成本摊薄到首次）。

---

## 5. 逐步改造计划

> 每项格式：**现状问题 → 改造内容 → 技术方案（引用示例）→ 涉及文件 → 验收标准**。
> 规模：S（≤2h）/ M（0.5d）/ L（1d+）。每项独立提交，提交后跑 §7 冒烟。

### 阶段 P0：地基（先让「改坏了」能被立刻发现）

#### P0.1 依赖与工程化配置 — S
- **现状问题**：webbox 无 `.venv`；`pyproject.toml` `package=true` 但 `packages=[]`（`ui/` 未打包，
  `babeldoc-webui` entry point 指向 `main:main` 勉强可用但 `ui` 包丢失）；无 dev 依赖、无 lint 配置。
- **改造内容**：
  - `uv sync` 生成 webbox 本地 `.venv`（nicegui>=3.16、babeldoc>=0.6.4 锁定版本）。
  - 修正 `pyproject.toml`：`[tool.setuptools] packages = ["ui", "ui.components", "core", ...]`
    （随 P1 落盘后再补 `core.*`）；新增 `[dependency-groups] dev = ["pytest", "ruff", "mypy"]`。
  - 新增 `[tool.ruff]`（line-length 110，规则参考 nicegui 仓库配置：E/F/I/UP/B）与
    `[tool.mypy]`（先只检查 `core/`，`strict` 渐进开启）；`[tool.pytest.ini_options]`
    `asyncio_mode = "auto"`（nicegui testing 需要）。
- **验收**：`uv run python main.py --port 8799` 能启动并打开首页；`uv run ruff check .` 可运行（记录基线告警数）。
- **风险**：babeldoc 安装较重（onnxruntime 等），首次 `uv sync` 可能数分钟。

#### P0.2 测试骨架 — M
- **现状问题**：P-12，无任何测试，后续每次重构都是盲改。
- **改造内容**（参考 `pytests/` 示例 + `deploy/tests/conftest.py`）：
  - `tests/conftest.py`：`pytest_plugins = ["nicegui.testing.plugin"]`；
    `isolated_data` fixture 把 `settings.json` / `history.json` 重定向到 `tmp_path`
    并重置 `settings_manager` / `history_manager` 单例（monkeypatch 模块属性）；
    `ui_user` fixture：数据隔离 + `importlib.reload` 页面模块以重新注册路由
    （deploy 已踩过的坑：user fixture 会清空已注册路由）。
  - 首批冒烟测试：`test_ui_home.py`——`user.open('/')` + `should_see('上传 PDF 文件')`、
    设置对话框可打开、语言选择项存在。
- **验收**：`uv run pytest -q` 全绿；冒烟能捕获「首页渲染失败」。
- **风险**：低。注意 conftest 路径相对 webbox 根目录。

#### P0.3 小清理（文档/一致性） — S
- 统一端口口径：`main.py` 默认 8765 的 help 文案、`README.md`「访问 http://localhost:8080」
  三处对齐（改 README 与 help 为 8765，或统一 8080——建议统一 8765 与代码一致）。
- README 增加「开发」小节（uv sync / pytest / 目录结构预告）。
- **验收**：`--help` 输出与 README 一致。


### 阶段 P1：领域层抽取（core/，UI 零改动，纯搬移+纯化）

> 原则：本阶段 `ui/` 的行为完全不变，只是把逻辑搬进 `core/` 并让 `ui/` 通过 shim 导入。
> 每搬一个模块，立即补该模块的单元测试（P0.2 骨架承接）。

#### P1.1 `core/providers.py`：服务商预设数据化 — S
- **现状问题**：P-08。`BUILTIN_PROVIDERS`（`settings.py:12-232`，200+ 行 list[dict]）
  与持久化、UI 辅助混在一个 783 行模块；`get_builtin_provider_by_id` 线性查找。
- **改造内容**：
  - 预设数据移到 `core/providers.py`，类型化为 `@dataclass(frozen=True) ProviderPreset`
    （id/name/default_base_url/icon/suggested_models）；
  - 模块级构建 `_PRESET_INDEX: dict[str, ProviderPreset]`（O(1) 查询）；
  - `get_builtin_provider_by_id()` 查索引；新增 `provider_presets()` 迭代器。
- **涉及文件**：`core/providers.py`（新）；`ui/components/settings.py` 改为
  `from core.providers import ...` re-export。
- **验收**：`test_providers.py`——索引命中/未命中、预设字段完整；settings 单测全绿。

#### P1.2 `core/models.py` + `core/settings_store.py`：设置模型与持久化分离 — M
- **现状问题**：P-07/P-08。dataclass（`settings.py:246-597`）与 `SettingsManager`
  （598-784）同文件；`save()` 非原子；`update_translation/pdf/rpc/paths/term_extraction`
  5 个「旧版兼容方法」疑似死代码。
- **改造内容**：
  - dataclass 整体移入 `core/models.py`（`ModelConfig / Provider / ProviderSettings /
    TranslationSettings / PdfSettings / RpcSettings / PathSettings / TermExtractionSettings / Settings`），
    保持字段与默认值**逐位一致**（迁移兼容性关键）；
  - `SettingsManager` 移入 `core/settings_store.py`：
    - `save()` 改原子写（tmp + `Path.replace`，对齐 `history.py:43-50` 的既有做法）；
    - 加载时容错：JSON 损坏时备份为 `settings.json.corrupt-<ts>` 并回退默认（**显式行为变更**：
      现状是直接抛错/空设置）；
    - 用 `rg "update_translation\(|update_pdf\(|update_rpc\(|update_paths\(|update_term_extraction\("`
      确认 5 个兼容方法在 `ui/` 无调用后删除（若有调用则保留并加 `@deprecated` 注释）；
    - `OpenAISettings`（旧版迁移用）：确认 `settings.json` 无旧格式残留逻辑后移入
      `migrate` 小节并注释标记（本阶段只移动不删除）。
  - 单例 `settings_manager` 保留在 store 模块末尾（`ui/components/settings.py` re-export）。
- **验收**：`test_settings_store.py`——round-trip（保存→重载字段一致）、原子写
  （模拟写失败不损坏原文件）、损坏文件备份回退；既有 settings 相关 UI 测试全绿。
- **风险**：dataclass 字段顺序/默认值漂移 → 用 round-trip 测试锁定。

#### P1.3 `core/history_store.py` — S
- **现状问题**：`HistoryManager`（`history.py`）已是纯领域代码，放在 `ui/components/` 名不副实。
- **改造内容**：移入 `core/history_store.py`，行为零改动；`ui/components/history.py` 变 shim。
  顺手：`uuid4_hex()` 的函数内 `import uuid` 提到模块顶。
- **验收**：`test_history_store.py`——add/records/clear/prune（文件被删后记录消失）全绿。

#### P1.4 `core/engine/`：翻译管线四件套 — L（本计划最大单项）
- **现状问题**：P-03/P-04/P-05。`run_translation`（`app.py:1368-1668`）300 行大函数
  混合「配置解析 / translator 创建 / 限流 / onnx 加载 / 术语表 / TranslationConfig 构造 /
  事件消费 / TOC 后处理 / 历史写入 / UI 刷新」；onnx 每次重载且阻塞事件循环。
- **改造内容**（把函数按数据流切成 4 个可独立测试的纯组件，UI 层只留「事件→元素」的胶水）：
  1. `engine/base.py`：
     - `JobEvent` 类型化：`@dataclass ProgressUpdate(progress, stage, stage_current, stage_total)`、
       `FileFinished(source, mono_pdf_path, dual_pdf_path)`、`JobError(message)`、
       `JobFinished(results)`——替代 `async_translate` 返回的裸 dict；
     - `TranslateEngine` Protocol：`async def translate(files, on_event, cancel_event) -> list[ResultFile]`。
  2. `engine/translator_factory.py`：抽出 `app.py:1333-1465` 的「ModelConfig →
     `OpenAITranslator` 创建」与「术语提取 translator 三分支」（主模型/已配置模型/自定义配置），
     函数化 `create_translators(settings) -> tuple[main, term, list[to_close]]`
     （返回 `to_close` 列表即资源所有权清单，为 P2.4 铺路）。
  3. `engine/config_builder.py`：抽出 `app.py:1517-1570` 的
     `build_translation_config(settings, file, translator, term_translator, doc_layout_model,
     glossaries, split_strategy) -> TranslationConfig`——纯函数，**重点单测对象**
     （Settings 每个字段 → TranslationConfig 字段的映射表逐字段断言，防重构漂移）。
  4. `engine/layout_model.py`：进程级 `DocLayoutModel` 懒加载单例
     （`_lock + _instance + _key(doclayout_host)`）：
     - `get_doc_layout_model(rpc_host: str | None)`：host 变化时重建；
     - 加载动作（`DocLayoutModel.load_onnx()`，秒级）由调用方包 `run.cpu_bound`
       （NiceGUI 环境）——P1 阶段先在函数内注释标明，P2.2 正式接入；
     - **显式性能变更**：第 2 次起翻译不再重载 onnx 模型（用户可感知：二次启动更快）。
  5. `engine/babeldoc_engine.py`：`BabelDocEngine.translate(...)`——
     内部 `import babeldoc...`（延迟导入保持在引擎内，UI/Job 不再触碰）；
     消费 `async_translate(config)` 事件流并翻译成 `JobEvent`；逐文件循环 +
     取消检查 + TOC 后处理调用（`core/postprocess/toc.py`，见 P1.6）都收进引擎。
- **UI 层临时形态**：`run_translation` 瘦身为「建 Job（P2 前暂用 PageState 承载）→
  调用 `BabelDocEngine.translate` → 事件里更新 UI 元素」，≤80 行。
- **验收**：
  - `test_config_builder.py` 字段映射逐位断言；
  - `test_jobs.py` 用 `FakeEngine`（yield 预设 JobEvent 序列）验证引擎事件协议；
  - 手工冒烟：真实翻译一个 2 页 PDF，二次翻译日志确认无第二次 `load_onnx`。
- **风险**：最高单项。缓解：先写 `test_config_builder` 锁定现状映射再搬移；
  保留 `run_translation` 原名作薄壳，UI 代码 diff 最小。

#### P1.5 `core/pipeline/`：monkeypatch 按关注点拆分 — M
- **现状问题**：P-09。`babeldoc_compat.py` 926 行混合 4 个补丁，每个补丁
  「源函数复制 + 修改」体量大，混排后难以单独回退/升级适配。
- **改造内容**：
  - 按文件 docstring 已有的编号拆为 4 个模块：`paragraph_fix.py`（P1）、
    `glossary_filter.py`（P2a 过滤规则 + `_is_reasonable_term`、P2b `parse_term_pairs`
    容错解析——这两者是纯函数，**直接可单测**）、`partial_match.py`（P3）、
    `placeholder_limit.py`（P4）；
  - `core/pipeline/__init__.py` 提供 `apply_patches() -> list[str]`（已应用的补丁名）
    与幂等保护（`_PATCH_APPLIED` 语义保留）；版本护栏（「与 0.6.4 逐行对齐，API 变更告警跳过」）
    逻辑统一收敛到 `__init__.py` 的 `_guard(module_attr, expected_hash_or_name)`；
  - 各补丁模块内部保持「先探测上游函数是否存在/签名匹配，再替换」的既有防御风格；
  - `ui/components/babeldoc_compat.py` 变 shim（`from core.pipeline import apply_patches` 等）。
- **验收**：`test_pipeline_patches.py`——`_is_reasonable_term` 边界用例（纯数字/标点/
  版本号/专名）、`parse_term_pairs`（正常 JSON/带说明文字/截断/空输入）；
  `apply_patches()` 二次调用幂等；手工翻译冒烟通过（补丁实际生效）。
- **风险**：补丁与 babeldoc 内部 API 强耦合，拆文件时**只移动代码不改逻辑**，
  避免引入行为差异；冒烟必须包含「自动术语提取」与「目录页 PDF」两类样本。

#### P1.6 `core/postprocess/toc.py` — S
- **现状问题**：`toc_generator.py`（407 行）为纯领域代码（fitz 解析 + 翻译 + 写书签），
  放在 `ui/components/` 下；`fitz` 在函数内延迟导入（好习惯，保留）。
- **改造内容**：移入 `core/postprocess/toc.py`，零逻辑改动；原路径留 shim。
- **验收**：`test_toc_parser.py`——`parse_toc_page_text` 样本（正常条目/拆行条目
  `1.1. ` + 标题行/无编号标题/页脚纯数字干扰）；`_merge_split_toc_lines` 用例。

#### P1.7 core 层类型与静态检查收尾 — S
- 为 `core/` 全部公共函数补类型注解 + docstring（中文，对齐现有风格）；
  `uv run mypy core/` 零错误（`disallow_untyped_defs` 对 core 开启）；
  `ruff check core/` 零告警。
- **验收**：`mypy core/ && ruff check core/ && pytest -q` 三连全绿。


### 阶段 P2：任务模型与后台执行（并发单元 = Job，事件驱动）

> 本阶段解决 P-02/P-04/P-05/P-06/P-10：全局注册表、`_safe_call`、事件循环阻塞、
> 上传内存/同名覆盖。UI 外观不变。

#### P2.1 `core/jobs/`：TranslationJob + JobManager — L
- **现状问题**：P-02。`_active_pages`/`_active_translators` 两个全局 set + 两把锁 +
  4 个 register/unregister 函数 + `_cancel_running_tasks`，状态散落且与 UI 对象（PageState）纠缠。
- **改造内容**（参考 `global_worker/main.py` 的 Worker 生命周期 +
  `deploy/ui/events.py` 的订阅模式）：
  - `translation_job.py`：
    ```python
    @dataclass
    class TranslationJob:
        id: str                      # uuid4_hex()
        files: list[JobFile]         # name/path
        status: JobStatus            # pending|running|done|error|cancelled
        progress: float = 0.0
        stage: str = ""
        results: list[ResultFile] = field(default_factory=list)
        error: str | None = None
        cancel_event: threading.Event
        _subscribers: list[Callable[[JobEvent], None]]
        # 方法：subscribe/unsubscribe/emit/cancel/finish
    ```
    事件订阅**在 Job 实例上**（每 Job 一份），UI 元素引用只存在于订阅回调闭包内，
    client 断开时 `unsubscribe()` 即完成解绑——`_safe_call` 的根因消失。
  - `job_manager.py`：`job_manager.submit(files, settings, engine) -> TranslationJob`
    内部 `background_tasks.create(_run(job))`（global_worker 的 `run()` 同款）；
    `running_jobs()`、`cancel_all()`（挂到 `app.on_shutdown`，替代
    `_cancel_running_tasks` + `_close_translators`）。
  - `run_translation`（UI 薄壳）：`ps.job = job_manager.submit(...)`，
    按钮状态由 `ps.job` 的 status 驱动。
- **涉及文件**：`core/jobs/*`（新）；`ui/app.py` 删除 24-95 行注册表与 `_safe_call`；
  `main.py` 的 `run()` 增加 `app.on_shutdown(job_manager.cancel_all)`。
- **验收**：`test_jobs.py`——FakeEngine 下 submit→progress 事件→done；cancel 中途
  （cancel_event 置位后引擎循环退出、status=cancelled、translator 被 close）；
  两个并发 Job 互不干扰；shutdown 时全部取消。
- **风险**：PageState→Job 的状态迁移牵动首页多处按钮逻辑；用「先加 Job、双写、
  再切读、最后删旧字段」的小步提交降低风险。

#### P2.2 阻塞工作移出事件循环 — M
- **现状问题**：P-04/P-05。`DocLayoutModel.load_onnx()`、`import babeldoc`、
  fitz 解析等同步重活直接跑在事件循环里，期间**所有**在线客户端的 UI 事件都排队。
- **改造内容**（参考 `progress/main.py` 的 `run.cpu_bound` + `ai_interface/main.py` 的 `run.io_bound`）：
  - `engine/layout_model.py`：`get_doc_layout_model()` 的 onnx 加载走
    `run.cpu_bound(_load_onnx)`（首次加载数秒 → 不再卡 UI；后续命中缓存直接返回）；
  - `babeldoc_engine.translate` 中引擎初始化（重导入 + 构建）包
    `await run.io_bound(...)`；`async_translate` 本身是 async 生成器，保持事件循环内消费；
  - 术语表文件读取（`Glossary.from_csv` 循环）包 `run.io_bound`；
  - `main.py` 的 mp start method（linux=forkserver）保持，与 `run.cpu_bound` 兼容
    （cpu_bound 子进程内不触碰 NiceGUI，只跑纯函数——`_load_onnx` 必须是模块顶层
    可 pickle 函数）。
- **验收**：手工验证——翻译进行中（onnx 首次加载窗口）打开第二个浏览器标签页
  交互无冻结；日志时间戳确认加载发生在子进程。
- **风险**：`run.cpu_bound` 要求函数可 pickle（不能是闭包/方法）→ `_load_onnx`
  设计为模块级函数；forkserver 下子进程导入开销可接受（一次性）。

#### P2.3 事件订阅取代 `_safe_call` — M（与 P2.1 同批交付）
- **现状问题**：P-10。后台任务直接 `ps.progress_bar.set_value(...)` 外包 `_safe_call`
  吞异常；客户端刷新/关闭后任务继续跑、事件被静默丢弃，进度/结果状态漂移。
- **改造内容**：
  - 首页渲染时：`ps.job_sub = ps.job.subscribe(on_job_event)`，回调内更新
    进度条/阶段标签/结果区（回调仍在事件循环线程执行，UI 操作安全）；
  - `client.on_disconnect` / 页面卸载：`ps.job_sub()`（退订）。**注意**：退订只断开
    UI，Job 继续在后台跑（用户刷新页面不中断翻译——这是当前 `_safe_call` 方案
    事实上已经支持的语义，保持）；
  - 可选增强（默认不做）：页面重开时若存在 running job，重新订阅并从 Job 当前
    快照（progress/stage/results）恢复 UI——「刷新后进度条接上」。
- **验收**：`test_jobs.py` 补——订阅/退订后事件不再触达回调；UI 冒烟：
  翻译中刷新页面，任务继续、重开页面（若实现了增强项）进度恢复。
- **风险**：低（纯替换，语义对齐现状）。

#### P2.4 资源所有权收归 Job + 临时目录隔离 — M
- **现状问题**：P-06。上传目录 `tmp/babeldoc-webui/` 全局共享、同名覆盖；
  translator 生命周期靠全局表管理。
- **改造内容**：
  - **上传**（`upload_section`，NiceGUI 3.x `FileUpload` API，
    见 `nicegui/elements/upload_files.py`）：
    - `await e.file.save(job_temp_dir / e.file.name)` 取代 `await e.file.read()` 整读
      ——`save()` 内部 1MB 分块异步写、大文件已 spool 磁盘，内存峰值从「整文件」
      降到 1MB 级（**显式性能变更**：大 PDF 上传内存占用显著下降）；
    - 临时目录改为**每 Job 独立**：`~/.cache/babeldoc-webui/jobs/<job_id>/`
      （`tempfile.mkdtemp(dir=...)` 或 mkdir），Job 结束（done/error/cancelled）
      延迟清理（结果文件在输出目录，上传原件保留至 Job 清理策略：默认
      保留最近 N 个 Job 目录，可配置）；
    - 同名文件因目录隔离不再冲突（**显式行为变更**：临时文件位置变化，
      对用户不可见）。
  - **translator**：Job 在 `_run` 内 `create_translators()`（P1.4 的
    `to_close` 清单），`finally` 逐个 close——删除 `_register_translator`/
    `_unregister_translator`/`_close_translators` 全局机制（`app.on_shutdown`
    时 `job_manager.cancel_all()` 后各 Job 的 finally 兜底 close）。
- **验收**：并发上传两个同名 PDF 不再互相覆盖（单测/手工）；翻译后
  `jps` 观察无泄漏的 httpx 连接（translator client 已 close）；Job 目录清理策略单测。
- **风险**：缓存目录清理策略涉及磁盘占用，默认保守（保留最近 10 个 Job 目录）。

#### P2.5 进度节流 — S
- **现状问题**：P-10（性能面）。每个 `progress_update` 事件（babeldoc 每段落级触发，
  高频）都直接驱动 UI 属性更新 → 大量 websocket 消息。
- **改造内容**：Job 的 `emit(ProgressUpdate)` 做时间节流（合并 100ms 内的连续
  更新，只转发最后一次；`FileFinished/Finished/Error` 永不节流）；
  参考 `progress/main.py` 的 `ui.timer(0.1, ...)` 拉取思想，但实现放在 Job 侧
  （订阅者无需感知）。
- **验收**：`test_jobs.py`——100 个连续 ProgressUpdate 在节流窗口内只产生 ≤2 次
  转发，最终值正确；UI 无跳变（进度单调递增）。

#### P2.6 一次性请求取消（模型测试等） — S
- **现状问题**：设置对话框的模型连通性测试（若有）等一次性网络请求无取消机制，
  快速切换服务商时旧请求覆盖新结果。
- **改造内容**：参考 `search_as_you_type/main.py`——`asyncio.create_task` +
  新请求到来 `task.cancel()` + `except asyncio.CancelledError` 静默。
  若当前无「模型测试」功能则本项合并进 P3.4（设置对话框改造时顺带实现
  「测试连接」按钮，正好用上该模式）。
- **验收**：快速连续点击测试按钮，只有最后一次结果生效。


### 阶段 P3：UI 模块化（视图层按 `modularization` 示例拆散）

> 本阶段 `ui/app.py` 从 1950 行降到 <150 行（只剩组装），页面代码全部落位。
> 功能与外观保持等价（CSS 除外，见 P3.1）。

#### P3.1 `ui/layout.py` + 静态 CSS — M
- **现状问题**：P-13。内联 CSS 每客户端重复注入；无统一页面骨架（theme 色板散落）。
- **改造内容**（参考 `modularization/theme.py` 的 `frame()` contextmanager +
  `deploy/ui/layout.py` 的 `page_frame`/静态 CSS 先例）：
  - `ui/layout.py`：
    - `@contextmanager def page_frame(title: str)`：统一 `ui.colors(...)` 色板、
      header（标题 + 设置按钮 + 历史入口）、主容器 `ui.column().classes('flex-1 ...')`
      （现在 header/主列骨架就在 `create_main_page` 里，整体迁入）；
    - `apply_theme()`：`app.on_startup` 一次性
      `ui.add_head_html('<link rel="stylesheet" href="/ui-static/main.css">', shared=True)`
      （`app.add_static_files(Path('assets/static'))`，参考 deploy 的 `ui-static` 约定；
      **显式变更**：CSS 从每客户端内联变为静态文件，外观不变、首屏更轻）。
  - `assets/static/main.css`：从 `create_app_for_client`（`app.py:1739+`）原样迁出。
- **验收**：截图比对首页/设置对话框无视觉差异；页面加载网络面板确认 CSS 为
  200 静态资源且每客户端只加载一次。

#### P3.2 `ui/pages/home_page.py` — M
- **现状问题**：P-01。`@ui.page('/')` 页面函数 + `create_app_for_client` 都在 app.py。
- **改造内容**（`modularization/home_page.py` 的 `content()` 模式）：
  - `home_page.py`：
    ```python
    def content() -> None:
        ps = PageState()
        register_page(ps)          # P2.1 后：Job 生命周期挂钩
        upload_section.build(ps)
        options_section.build(ps)
        progress_section.build(ps)
        results_section.build(ps)
        history_section.build(ps)
    ```
  - `ui/app.py`：
    ```python
    @ui.page('/')
    def _home():
        with layout.page_frame('BabelDOC WebUI'):
            home_page.content()
    ```
  - `PageState` 移入 `ui/components/page_state.py`（纯 UI 状态：上传列表、
    元素引用；**不再持有** is_running/progress/error——这些已在 Job 上，P2.1 完成）。
- **验收**：UI 冒烟全绿；`ui/app.py` < 150 行；首页路由行为不变。

#### P3.3 `ui/components/sections/*`：五个分区模块 — M
- **现状问题**：P-01/P-11。上传/选项/进度/结果/历史五个 `create_*` 函数（合计
  ~800 行）全在 app.py；列表全量重建。
- **改造内容**（每模块一个 `build(ps)` 入口，内部私有 helper）：
  - `upload_section.py`：`handle_file_upload`（P2.4 的 `e.file.save()` 落 Job 目录）+
    文件列表。文件列表改**增量更新**：新增行 `append`、删除只移除对应 row
    （row 与 file_info 用闭包/元素属性绑定；**显式性能变更**：不再全量重建，
    外观不变）；
  - `options_section.py`：语言/页码范围/目标语言等选项（原 `create_options_section`）；
  - `progress_section.py`：进度条/阶段标签/开始/取消按钮——
    绑定驱动（`bind_value_from(ps.job, 'progress')`，global_worker 模式；
    取消按钮 `on_click=ps.job.cancel`）；
  - `results_section.py`：结果卡片，`ui.download(path)` 保持；
    增量 append（新结果追加行，不重建整表）；
  - `history_section.py`：历史记录列表。条目多（>30）时改 `ui.table`
    （列：类型/文件名/时间/下载按钮，row slot 渲染），`ui.timer(5s)` 低频刷新
    仅在对话框打开时启用（参考 `infinite_scroll/` 的分页思想控制 DOM 规模）。
- **验收**：UI 冒烟 + 视觉对比；上传 3 个文件→删 1 个→再传 1 个，DOM 行数正确
  且无整表闪烁；历史 50 条时打开对话框 <500ms。

#### P3.4 `ui/components/settings/*`：设置对话框拆 6 Tab 模块 — L
- **现状问题**：P-01。设置对话框（`app.py` 内 ~450 行：服务商/模型管理 +
  翻译/性能/高级 + PDF 输出 + 文档处理 + RPC + 路径）是最大的单块 UI。
- **改造内容**（每 Tab 一个模块，`build(dialog_container)` 入口；
  数据结构仍绑定 `settings_manager.settings.*` 的 `bind_value`，**绑定语义不变**）：
  - `dialog.py`：`open_settings_dialog()`——`ui.dialog` + `ui.tabs` 装配 6 个 Tab，
    底部「保存」按钮调 `settings_manager.save()`（现状是各变更即 save 还是按钮 save，
    以现状为准保持）；
  - `providers_tab.py`：服务商列表 + 增删 + 模型卡片（ModelConfig 表单）——
    最大的 Tab，内含 P2.6 的「测试连接」按钮（`run.io_bound` + task 取消）；
  - `translation_tab.py` / `pdf_tab.py` / `doc_processing_tab.py` /
    `rpc_tab.py` / `paths_tab.py`：各 `create_*_tab` 原样搬入。
  - 保存防抖（若现状为变更即存）：`ui.timer(0.5, save_if_dirty, once=False)`
    脏标记合并写盘（**显式性能变更**：连续拖动/输入期间磁盘写从 N 次降为 1 次，
    语义等价）。
- **验收**：设置各 Tab 打开/保存/重载后值正确（UI 测试覆盖：改 QPS→保存→
  重开对话框值保持）；providers 增删模型、切换 selected 的 UI 测试。
- **风险**：Tab 间共享的 `settings_manager` 绑定对象引用需逐字核对
  （`bind_value` 目标是 dataclass 实例属性，拆模块后 import 路径变化但对象同一）。

#### P3.5 进度/状态绑定驱动收尾 — S（与 P3.3 progress_section 同批）
- 确认全部「状态→元素」路径均为 binding 或 Job 事件回调，删除残留的
  `ps.is_running` 等 UI 侧影子状态（唯一事实源 = `Job.status/progress/stage`）。
- **验收**：代码搜索无 `ps.is_running` 残留；开始/取消/完成三态按钮切换正常。

#### P3.6 结果下载与文件存在性 — S
- 现状 `show_results` 中下载按钮 `lambda p: ui.download(p)` 对已删除文件无防护
  （`download_file()` 有 exists 检查但未被按钮使用——疑似死代码）。
- **改造内容**：下载按钮统一走 `download_file`（存在性检查 + `ui.notify` 错误提示）；
  结果行渲染时文件已不存在的显示「文件缺失」态（灰色，无下载按钮）。
- **验收**：删除一个结果 PDF 后刷新，对应行显示缺失态；下载正常文件可用。


### 阶段 P4：持久化与运行时健壮性

#### P4.1 settings 原子写 + schema_version + 迁移框架 — S
- **现状问题**：P-07（P1.2 已改原子写）；settings.json 无版本号，未来加字段只能靠
  `data.get(k, default)` 散落处理，旧配置升级无路径。
- **改造内容**：
  - `Settings` 序列化增加 `"schema_version": 1` 顶层字段；
  - 加载器：读版本号 → 按 `MIGRATIONS: dict[int, Callable[[dict], dict]]`
    逐级迁移（v0=无版本旧格式 → v1）；当前只需登记 v0→v1 的空迁移占位 + 文档；
  - 未知更高版本号：拒绝加载并备份原文件（防跨版本降级覆盖）。
- **验收**：`test_settings_store.py`——v0 旧格式加载成功；未知高版本拒绝 + 备份文件生成。

#### P4.2 history 上限与过期清理 — S
- **现状问题**：`history.json` 只增不减（`_prune_missing` 只删文件失效项），
  长期使用记录无限增长；结果 PDF 本身也无清理策略。
- **改造内容**：
  - `HistoryManager.add()` 后按上限裁剪（默认保留最近 `max_records=200`，
    可配置项加入 `PathSettings`），被裁掉记录**只删记录不删文件**（保守）；
  - 启动时一次性清理 `~/.cache/babeldoc-webui/jobs/` 中超过 `job_dir_retention=10`
    个的旧 Job 临时目录（P2.4 策略的启动兜底）。
- **验收**：单测——add 201 条后 records 长度 = 200 且最旧记录被裁；Job 目录保留策略单测。

#### P4.3 日志落盘 — S
- **现状问题**：仅 stdout 日志；翻译类应用的排障需要文件日志（大文件/长任务）。
- **改造内容**（参考 `deploy/ui/logging_setup.py` 的按日滚动实现）：
  - `main.py` 增加 `--log-file`（默认 `~/.cache/babeldoc-webui/webui.log`）与
    `--log-level`；`RotatingFileHandler(maxBytes=5MB, backupCount=3)`；
  - 保持 `httpx/httpcore/openai/pdfminer` 的降噪逻辑（`main.py:30-31` 现状）。
- **验收**：启动后翻译一次，日志文件存在且包含翻译路径日志；重启不丢历史日志。

#### P4.4 （可选）用户态 UI 偏好 — S
- `ui.run(storage_secret=...)` + `app.storage.user` 存主题/语言偏好
  （`single_page_app` 示例 + `deploy/ui/app.py:120` 同款）；不侵入 settings.json。
- **验收**：刷新/重开页面后主题偏好保持。

---

### 阶段 P5：测试与质量收尾

#### P5.1 core 单测补全至高覆盖 — M
- 目标：`core/` 行覆盖 ≥ 85%（`pytest-cov` 加 dev 依赖）。
- 补测重点（P1/P2 各条「验收」中未覆盖的残余）：
  - `translator_factory`：三分支（主模型/已配置术语模型/自定义术语配置）的
    kwargs 组装（mock `OpenAITranslator` 构造，断言参数）；
  - `layout_model`：缓存命中/失效（host 变化重建）；
  - `job_manager.cancel_all` 与 shutdown 时序。
- **验收**：`pytest --cov=core` 达标；CI 可重复。

#### P5.2 UI 测试矩阵 — M
- 基于 P0.2 的 `ui_user` fixture 扩展（`pytests/tests/test_with_user.py` 风格）：
  - 首页渲染/上传交互（User fixture 下 mock upload 事件）/开始按钮无模型时提示；
  - 设置对话框：开 Tab、改 QPS、保存、重开持久；
  - 结果区：注入假 history 记录 → 渲染/下载按钮存在；文件缺失态（P3.6）。
- **验收**：上述用例全绿；新增 UI 改动必须先补用例（写入 CONTRIBUTING 式注释）。

#### P5.3 FakeEngine 集成流 — S
- `tests/test_jobs.py` 扩展为端到端（不触网）：FakeEngine 按脚本
  progress→stage→file_finished→finished 产出事件，验证 Job 状态机、
  节流、取消、历史写入（history_manager 隔离到 tmp）、结果文件登记。
- **验收**：一条测试覆盖「完整成功流」，一条覆盖「中途取消流」，一条覆盖「错误流」。

#### P5.4 静态检查与文档 — S
- `ruff check .` 全项目零告警（含 `ui/`）；`mypy core/` 零错误（ui 层
  `ignore_missing_imports` 豁免 babeldoc 内部模块）；
- 删除迁移期 shim（`ui/components/settings.py` 等 4 个），import 全部切到 `core.*`；
- `README.md` 更新：目录结构图、开发流程（uv sync/pytest/ruff）、
  「如何扩展」三节（新增服务商预设=改 `core/providers.py`；新增引擎=实现
  `TranslateEngine` Protocol；新增页面=`ui/pages/` 加模块 + 路由）。
- **验收**：`ruff check . && mypy core/ && pytest -q` 全绿；README 与代码一致。

---

### 阶段 P6：可选拓展（按需排期，不阻塞 P0–P5）

#### P6.1 引擎多后端 — M
- `engine/base.py` 的 `TranslateEngine` Protocol 已就位（P1.4）；补
  引擎注册表（`ENGINES: dict[str, type[TranslateEngine]]`，当前只注册
  `babeldoc`）+ settings 增加 `engine` 字段（默认 `babeldoc`），为 pdf2zh-next
  等同类工具接入留口（README 已提及 retain-pdf/pdf2zh 同类对比）。
- **验收**：注册表单测；切换字段不影响 babeldoc 默认路径。

#### P6.2 REST API（无头/脚本化） — M
- `modularization/api_router_example.py` 模式：`app.include_router(api.router)`，
  `router = APIRouter(prefix='/api')`：
  - `POST /api/jobs`（提交翻译：multipart 上传 + 参数）→ 返回 job_id；
  - `GET /api/jobs/{id}`（状态/进度/结果 URL）；
  - `GET /api/jobs/{id}/results/{file_id}`（文件下载）；`DELETE /api/jobs/{id}`（取消）。
- 复用 `job_manager`，零业务重复。
- **验收**：`curl` 冒烟：提交→轮询→下载；与 UI 同时在线互不干扰。

#### P6.3 界面 i18n — M
- 参考 `deploy/ui/i18n.py` 的 `tr()`/多语言包模式；首页+设置常用文案
  中/英双语（现状全中文硬编码）。
- **验收**：语言切换后关键文案变化；默认中文不变。

#### P6.4 容器化 — M
- `nicegui/examples/docker_image` + `examples/ros2`（compose 多服务：
  WebUI + 可选 doclayout RPC 服务）模式；提供 `Dockerfile` +
  `docker-compose.yml`（babeldoc 的 onnx 依赖体量大，基础镜像分层缓存）。
- **验收**：`docker compose up` 后浏览器可用；与裸跑行为一致。


---

## 6. 实施顺序与依赖

```
P0.1 环境/pyproject ─┬─→ P0.2 测试骨架 ─→ P0.3 小清理 ─┐
                     │                                │
                     ▼                                ▼
        P1.1 providers ─→ P1.2 models/store ─→ P1.3 history
                                     │
        P1.6 toc（独立，可并行）      ▼
        P1.5 pipeline（独立，可并行） P1.4 engine 四件套（最大单项）
                                     │
                                     ▼
              P2.1 Job/JobManager ─→ P2.3 事件订阅（同批）
                     │           └─→ P2.5 进度节流
                     ▼
              P2.2 run.cpu_bound/io_bound ─→ P2.4 资源/临时目录 ─→ P2.6 请求取消
                     │
                     ▼
        P3.1 layout+CSS ─→ P3.2 home_page ─→ P3.3 sections ─→ P3.5 绑定收尾
                                                    │
                                                    ▼
                                            P3.4 settings 六 Tab ─→ P3.6 下载防护
                     │
                     ▼
        P4.1 schema/迁移 ─ P4.2 上限清理 ─ P4.3 日志 ─ P4.4(可选)
                     │
                     ▼
        P5.1 core 覆盖 ─ P5.2 UI 矩阵 ─ P5.3 FakeEngine 流 ─ P5.4 收尾(删 shim)
                     │
                     ▼
        P6.x 可选项（按需求排期）
```

**依赖要点：**
- P1 内部：P1.4 依赖 P1.2（需要 `core/models.py` 的 Settings 类型）；P1.1/P1.3/P1.5/P1.6 相互独立，可任意顺序/并行。
- P2.1 必须在 P1.4 之后（Job 要调用引擎接口）；P2.2/P2.4 依赖 P2.1 的 Job 结构。
- P3 全部依赖 P2.1（PageState 瘦身、按钮绑定 Job）；P3.1 可与 P2 并行准备（CSS 迁出不依赖 Job）。
- **每阶段合并条件**：`uv run pytest -q` 全绿 + §7 冒烟清单通过 + 独立 git commit
  （提交信息前缀 `refactor(webbox): P1.4 ...`）。

**显式行为变更总清单**（除以下 8 条外，用户可感知行为不变）：

| # | 变更 | 用户影响 |
|---|------|----------|
| 1 | 二次翻译不再重载 onnx 布局模型（P1.4） | 正面：更快 |
| 2 | 上传分块落盘 + 每 Job 独立临时目录（P2.4） | 正面：大文件内存降、同名不再覆盖 |
| 3 | 临时文件位置 `tmp/babeldoc-webui` → `~/.cache/babeldoc-webui/jobs/<id>`（P2.4） | 中性：对用户不可见 |
| 4 | settings.json 损坏时备份回退默认（P1.2） | 正面：不再直接炸 |
| 5 | settings 保存防抖合并写盘（P3.4） | 中性：落盘时机略延后（≤0.5s） |
| 6 | settings.json 增加 `schema_version` 字段（P4.1） | 中性：向后兼容 |
| 7 | history 记录上限 200（只删记录不删文件）（P4.2） | 中性：老记录从列表消失，文件仍在 |
| 8 | CSS 静态文件化（P3.1） | 中性：外观不变 |


---

## 7. 验证策略

### 7.1 自动化（每阶段合并前必跑）

```bash
cd webbox
uv sync
uv run pytest -q                 # 单测 + UI 测试
uv run ruff check .
uv run mypy core/                # P5.4 前仅 core 强制
uv run pytest --cov=core -q      # P5.1 起
```

### 7.2 手工冒烟清单（每阶段一次，真实 PDF，~10 分钟）

1. **启动**：`uv run python main.py --port 8799`，访问首页无报错、截图存 `docs/screenshots/<phase>/`。
2. **设置**：打开设置 → 各 6 个 Tab 逐一展开/收起 → 改 QPS 与语言 → 保存 →
   重启进程 → 重开设置确认值持久。
3. **上传**：上传 1 个小 PDF + 1 个 20MB 级 PDF，观察上传区列表；同名文件连传两次确认不互相覆盖。
4. **翻译**（有可用 API Key 时）：开始翻译 → 进度条/阶段文字推进 → 完成 →
   结果区出现 mono/dual 卡片 → 下载可用 → 历史区出现记录。
5. **取消**：翻译进行中点取消 → 提示「正在取消」→ 任务停止、按钮恢复。
6. **刷新**：翻译进行中刷新页面 → 任务后台继续 → 完成后历史区可见结果。
7. **性能观察**：首次翻译时打开第二个标签页点 UI（按钮/Tab）确认无冻结
   （P2.2 后）；应用日志确认 `load_onnx` 仅出现一次（P1.4 后）。
8. **退出**：Ctrl+C 正常退出，无未关闭 translator 的告警日志。

### 7.3 回归基线

- P0 阶段对**现状**跑一遍 §7.2 并截图存档（改造前基线），之后每阶段截图比对。
- babeldoc 升级（0.6.x → 新版本）时必跑：`test_pipeline_patches.py` +
  冒烟 4/5（补丁兼容性）。

---

## 8. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| P1.4 管线拆分引入翻译行为漂移（字段映射错一个 → 翻译参数错误） | 高 | 先写 `test_config_builder.py` 锁定现状映射再搬移；搬移后同 PDF 对比两次翻译的日志参数；保留 `run_translation` 薄壳便于回滚 |
| monkeypatch 与 babeldoc 版本耦合，拆文件时误改逻辑 | 高 | P1.5 只移动不修改；`apply_patches()` 版本护栏保留；冒烟必含术语提取 + TOC 页样本 |
| `run.cpu_bound` 子进程 pickle/forkserver 兼容问题 | 中 | `_load_onnx` 模块级纯函数；P0 阶段先用独立脚本验证 cpu_bound + forkserver 组合 |
| 全局单例（settings/history/job_manager）在多 uvicorn worker 下失效 | 中 | 文档明确「单进程部署」；`ui.run` 默认单 worker；多实例需求走 P6 前重新设计（参考 `redis_storage` 示例） |
| PageState→Job 状态迁移牵连首页多处交互，UI 测试不足导致回归 | 中 | P2.1 采用「双写→切读→删旧」三步提交；P3.3 的 sections 拆分在 Job 稳定后进行 |
| 大 PDF 上传内存峰值（现状整读）改造不彻底 | 低 | P2.4 用 `FileUpload.save()`（NiceGUI 官方 API，1MB 分块 + 磁盘 spool）；冒烟 20MB 文件 |
| 历史/Job 临时目录清理策略误删用户文件 | 中 | 保守默认：只删 Job 临时目录与超限记录，**永不自动删输出 PDF**；策略可配置并写日志 |
| 改造周期长，期间功能需求插入 | 低 | 每项独立提交、行为等价，任意阶段可暂停；新需求落在 `ui/components/sections` 或 `core/` 对应模块，不破坏分层 |


---

## 9. 附录：关键代码位置索引

### 9.1 webbox 现状（改造前）

| 位置 | 内容 |
|------|------|
| `webbox/main.py`（43 行） | 入口：argparse（port 默认 8765）/ logging / mp start method（linux=forkserver） |
| `webbox/ui/app.py:24-95` | `_active_translators` / `_active_pages` 全局注册表 + `_safe_call` |
| `webbox/ui/app.py:114-160` | `PageState`（UI 状态） |
| `webbox/ui/app.py:988-1057` | `create_upload_section`（上传 + 文件列表） |
| `webbox/ui/app.py:1060-1330` | 设置对话框（6 Tab：服务商/翻译/PDF/文档处理/RPC/路径） |
| `webbox/ui/app.py:1368-1668` | `run_translation`（管线组装大函数） |
| `webbox/ui/app.py:1677-1733` | `show_results` / `download_file` |
| `webbox/ui/app.py:1736-1915` | `create_app_for_client`（内联 CSS + 页面骨架） |
| `webbox/ui/app.py:1917+` | `run()`（`ui.run` 入口） |
| `webbox/ui/components/settings.py`（783 行） | `BUILTIN_PROVIDERS`（12-232）/ dataclass（246-597）/ `SettingsManager`（598-784，`save` 614-623 非原子） |
| `webbox/ui/components/history.py`（95 行） | `HistoryManager`（原子写 43-50） |
| `webbox/ui/components/babeldoc_compat.py`（926 行） | 4 个 monkeypatch（P1 段落重分行 / P2 术语+容错 JSON / P3 部分匹配 / P4 阈值 40→120，见 `:915`） |
| `webbox/ui/components/toc_generator.py`（407 行） | TOC 提取/翻译/写书签（纯领域） |

### 9.2 参考示例速查

| 示例 | 路径 | 学到的模式 |
|------|------|-----------|
| modularization | `nicegui/examples/modularization/` | 页面模块化、`theme.frame()`、`APIRouter`、自定义元素类（`message.py`） |
| global_worker | `nicegui/examples/global_worker/main.py` | Worker 类 + `app.on_startup` + `background_tasks` + `bind_value_from` |
| threaded_nicegui | `nicegui/examples/threaded_nicegui/main.py` | `Event` 发布/订阅解耦后台与 UI |
| progress | `nicegui/examples/progress/main.py` | `run.cpu_bound` + `Manager().Queue` + `ui.timer` |
| ai_interface | `nicegui/examples/ai_interface/main.py` | `run.io_bound`、upload 异步处理、`props('loading')` |
| search_as_you_type | `nicegui/examples/search_as_you_type/main.py` | task 取消防抖 |
| single_page_app | `nicegui/examples/single_page_app/` | `storage_secret`、`app.storage.user`、子页面 |
| pytests | `nicegui/examples/pytests/` | `nicegui.testing.plugin`、`User` fixture |
| generate_pdf | `nicegui/examples/generate_pdf/main.py` | `ui.download` |
| fastapi / redis_storage / sqlite_database / docker_image | `nicegui/examples/...` | REST 扩展 / 存储后端 / 容器化（P6 用） |
| 同仓库 deploy | `llms-deploy/deploy/` | `ui/events.py` EventBus、`ui/layout.py` page_frame、`ui/i18n.py`、`ui/logging_setup.py`、`tests/conftest.py` 数据隔离 |

### 9.3 术语

| 术语 | 含义 |
|------|------|
| Job | 一次翻译任务（文件集 + 参数 + 生命周期），`core/jobs/translation_job.py` |
| Engine | 翻译执行器抽象（`TranslateEngine` Protocol），当前唯一实现 `BabelDocEngine` |
| Shim | 迁移期兼容模块，仅 re-export 新位置符号 |
| 冒烟 | §7.2 手工验证清单 |

