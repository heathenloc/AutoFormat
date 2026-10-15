# 第八步首批交付：本地入口、任务恢复与 Windows 测试包

本增量把已完成的预览与反馈工作区接到双文件入口。用户从同一个本地应用上传 Brief 和论文原稿，先完成待确认项，再生成 V1，随后进入预览微调和历史分支；关闭并重启宿主后，可从任务列表找回已有任务。实际编辑继续使用已验证的类型化规则，V0 与已发布文件保持不变。

## 1. 首页与恢复

- 首页接受 DOCX／PDF／TXT Brief，以及 DOCX 论文，显示大小限制与 Brief 模型处理说明；复用现有安全上传和解析流程，不要求首轮选区或反馈文字。
- 有待确认项时打开编辑前确认面板；未回答或仅暂缓不会触发 V1。无待确认项时由既有首次发布器直接执行可靠规则。
- 上传失败保留文件选择；相同文件的重试复用内存中的请求 ID。即使服务器已完成而响应丢失，重试也不会新建重复任务或初稿。
- 按创建顺序分页展示任务，每页最多 50 条，包含工作起点与版本数；列表不返回论文正文、原文件名或磁盘路径。工作区可返回任务列表，再重开任务恢复问题、版本与反馈进度。
- 会话令牌只在页面内存中使用，进入页面后删除启动片段，不写入浏览器存储。刷新页面需从宿主重新打开；退出重启时生成新令牌，旧令牌失效。

新增鉴权路由：`GET /api/application`（运行模式、上传能力与文件上限）及 `GET /api/tasks?before={cursor}`（任务目录）。契约分别为 `application-info/1.0` 和 `task-catalog/1.0`，同步导出到 `contracts/` 和 API schema 副本。

## 2. 完整本地宿主

`autoformat.desktop_host` 在随机回环端口绑定既有 API，接入项目内 Brief Parsing、副本资源、真实 DOCX 编辑器、LibreOffice、PDF.js 与构建后的网页，使用系统浏览器打开首页。无需启动独立解析应用或手动传递 Bundle。

启动前检查 Python 3.12、Node.js 24、.NET 10、编辑器和 LibreOffice 哈希、PDF.js 固定版本资源，以及实际字体文件内容。字体指纹由真实文件集合计算，不能据此断言学校要求的全部字体已经安装。`--check` 只检查组件，不创建任务数据库或启动服务。

模型凭据从解析副本支持的环境配置读取，禁止放入桌面配置 JSON；日志禁用内容记录与远程遥测。未配置真实服务时拒绝运行，只有显式 `--demo` 才使用离线演示解析器，首页明显标注该模式。依赖异常使用固定诊断，避免输出密钥或私有配置。当前 Windows 不具备复制版要求的 Linux 硬解析隔离，因此生产／强制进程隔离配置会被拒绝，不静默绕过。

默认任务存储为 `%LOCALAPPDATA%/AutoFormat/tasks`；尚无新目录时自动沿用包含数据库的旧 `%LOCALAPPDATA%/EasyFormat/tasks`；可通过 `--store` 指定另一用户数据目录。退出后重新启动会读取原任务树，反馈、决定与历史分支仍由原有持久化机制恢复。

开发启动先根据 `desktop/config.example.json` 填写真实组件路径及哈希，再执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m autoformat.desktop_host --config <配置文件> --check --demo
.\.venv\Scripts\python.exe -X utf8 -m autoformat.desktop_host --config <配置文件> --demo
```

## 3. 可校验的 Windows 测试分发包

`scripts/build_windows_bundle.py` 使用明确清单复制应用源码、解析副本／提示词／领域包、契约、网页、编辑器、PDF.js 及其依赖、Python 运行依赖。依赖闭包读取当前本地 `pyproject.toml`，避免 editable 元数据滞后漏带新增库。不会打包 `.venv`、密钥、任务存储、论文或原 Brief 项目；依赖许可证和包元数据随库保留。

产物为 `runtime/releases/` 中的新目录和 ZIP，拒绝覆盖已有包。`bundle-manifest.json` 列出文件 SHA-256 和依赖版本；启动前拒绝缺失、变更、额外缓存及路径重定向。该清单用于一致性校验，不是发布者数字签名。

测试包的 `Start-AutoFormat.cmd` 使用 Python `-I -S -B`，仅导入应用内的模块和依赖，配置与任务数据放在包外。目标电脑仍须安装 64 位 Python 3.12、Node.js 24、.NET 10 及 LibreOffice。包内示例配置已填写所带编辑器的相对路径与哈希；外部组件须自行核对。完整使用方法见 [desktop/README.md](../desktop/README.md)。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/export_desktop_schemas.py
.\.venv\Scripts\python.exe -X utf8 scripts/build_windows_bundle.py
```

`scripts/smoke_windows_bundle.py` 必须用基础 Python 的 `-I -S -B` 执行，验证依赖确实来自包内，并走双文件上传、真实字号／对齐修改、PDF 渲染、PDF.js／DOCX 索引、上传重放、新会话恢复与历史哈希保护；最后再次校验包目录没有新增缓存或运行数据。此检查使用显式演示解析，不能替代真实模型准确率评估。

## 4. 验收与剩余边界

本轮后端全量 291 条通过，最终桌面专项 15 条通过，覆盖全量运行启动后追加的打包依赖回归。启用固定哈希 LibreOffice 后，常规浏览器 33 条通过，真实反馈编辑及历史兄弟分支专项 5 条通过，共 38 个浏览器场景。TypeScript／Vite 构建、契约模型与 schema 副本一致性、补丁格式检查均通过。

新增测试覆盖任务鉴权与分页、重启恢复、配置与日志保护、字体内容指纹、包完整性、当前依赖声明，以及首页双文件上传、编辑前确认、重开任务和丢失响应重试。浏览器样本固定独立的网页及编辑器副本，避免同时运行的后端构建改变已固定的组件。

更名前已归档的测试包为 `runtime/releases/EasyFormat-Windows-test-20261008.zip`，大小 64,460,799 字节，旁边提供 ZIP SHA-256 文件。解压后使用基础 Python 的 `-I -S -B` 完成启动检查及端到端验证：实际正文改为 14pt／居中，DOCX 与 PDF.js 索引可读，相同上传不增加版本，重启找回 V1 且旧会话失效，V0 与已发布 DOCX／报告／PDF 哈希不变，包内无新增缓存或任务数据。此验证使用显式演示解析和真实编辑器／渲染器。包内 409 个应用、解析、网页及编辑器文件与最终工作区产物逐项一致；NuGet 依赖许可和元数据已附带。

这是第八步的首批交付。WebView2 原生外壳、独立 EXE 安装器、安装／升级与其他目标电脑验收尚未完成；当前测试包不能声称免依赖安装。Word 对照分页、目录／页码缓存刷新、代表性学校论文的首次解决率与真实模型样本验收仍需补齐。首次忽略学术要求的发布后重答界面、独立可靠反馈片段的执行也继续保留为未完成项，未放宽原有整轮 ready 与编辑安全约束。
