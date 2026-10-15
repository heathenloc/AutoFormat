# AutoFormat 项目更名记录

日期：2026-10-08。项目名称由 EasyFormat 统一改为 **AutoFormat**。

## 已更新范围

- 产品需求、技术架构、Brief Parsing 设计、模块说明、开发记录、宣传文案及相互引用。三份主文档现为 `AutoFormat_PRD.md`、`AutoFormat_Technical_Architecture.md` 和 `BriefParsing_AutoFormat.md`。
- Python 分发包 `autoformat-api` 与代码包 `autoformat`；前端包 `autoformat-web`；.NET 项目、命名空间与产物 `AutoFormat.DocxIndex`、`AutoFormat.DocxEditor`。
- 工作台品牌及 A 字标、浏览器标题、错误提示、报告标题、下载文件名、桌面启动器 `Start-AutoFormat.cmd` 和测试包构建名称。
- 宣传网页中英文文案、页面标题、描述、无障碍名称和 A 图标；语言事件及 Benchmark 数据变量改用 `autoformat`。

## 历史兼容与工作区

开发工作区继续使用真实路径 `E:\EasyFormat`，文档中的本机命令保留该路径。不得在工作区外新建或搬移项目，也不修改只读的 `E:\Brief Parsing` 来源目录。

已有 `https://easyformat.local/contracts/...` JSON Schema `$id` 是版本化协议标识，保留原值及契约形状，导出脚本继续生成相同标识。产品更名不改变规则、版本、哈希或历史语义。复制来源清单 `SOURCE_SNAPSHOT.json` 不改写；复制版模型提示中的产品名称已更新，相应文件哈希记录在 `LOCAL_CHANGES.json`。

新安装默认使用 `%LOCALAPPDATA%/AutoFormat/tasks`。若新目录尚不存在，且旧 `%LOCALAPPDATA%/EasyFormat/tasks/versions.sqlite3` 存在，则继续打开旧目录，不搬移任务或改写历史 DOCX、报告和预览。已显式指定的 `--store` 始终优先；两个目录均存在时默认使用 AutoFormat，可通过 `--store` 打开旧目录。

新界面发送 `X-AutoFormat-Session`；本地 API 仍接受旧 `X-EasyFormat-Session`，保持相同会话与来源校验。两种头同时提供且不一致时拒绝请求。宣传页优先读取 `autoformat-site-language`；缺少新值时继承旧语言偏好。

已归档的更名前测试包与历史任务文件保持原样；旧测试记录与截图不作批量更名，新测试运行产物继续写入 `runtime`。开发记录中的旧包名是历史产物引用。之后重新构建的应用与测试包使用 AutoFormat。

## 开发环境更新

更新既有虚拟环境的本地包元数据，然后重新构建前端与 .NET 产物：

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y easyformat-api
.\.venv\Scripts\python.exe -m pip install --no-deps -e apps/api
dotnet build services/docx_engine/AutoFormat.DocxEditor
cd apps/web
pnpm build
```

桌面入口改为 `python -m autoformat.desktop_host`。外部配置文件若固定了旧 DLL 路径和哈希，须针对新构建产物重新核对；应用仍会拒绝不一致的哈希。浏览器测试变量现在使用 `AUTOFORMAT_TEST_*`。

宣传网页仍是 `site/` 中的 GitHub Pages 静态页面；本次更新项目内源码与本地预览，未修改 GitHub Pages 配置或发布远端。


## 本轮验证

- 前端类型检查与生产构建通过；两个 .NET 项目构建零警告、零错误，索引与编辑检查通过，学术编辑核心 243 项检查通过。
- 应用完整回归 296 项通过、6 项跳过；跳过项需要显式配置固定哈希的 LibreOffice。真实编辑／渲染另由浏览器补跑及隔离测试包链路验证。
- Brief Parsing 复制版 391 项通过、2 项 Windows 环境跳过；原始 180 文件来源核验为 8 项已记录改动、0 项不匹配。
- 旧任务副本恢复：1 个任务、2 个版本、1 份旧品牌报告可正常读取，学术规则可重放，原存储与已发布文件哈希不变。
- 浏览器标准回归 31 项通过；提供已核验的真实渲染器后，补跑其余 7 个编辑／中文选区／历史分支场景，全部通过，合计 38 项。
- 宣传页 9 种宽度 × 中英文共 18 种布局检查通过；旧语言偏好继承、禁用存储、禁用脚本、手机菜单及 Pages 子路径通过，无脚本错误或资源加载失败。
- 新包：`runtime/releases/AutoFormat-Windows-test-20261008.zip`（64,462,438 字节），SHA-256 见相邻 `.zip.sha256` 文件。使用 `-I -S -B`、离线演示解析和真实编辑器／LibreOffice／PDF.js 完成上传幂等、实际修改、预览文字索引、重启恢复与原稿／历史保护验证。

测试包验证使用短工作路径 `runtime/af-smoke`。首次使用较长的 `runtime/autoformat-bundle-smoke` 时，LibreOffice 退出码为 0 但未生成 PDF；缩短工作路径后同一测试包通过。此轮未改变渲染器实现，Windows 长路径场景仍需单独验收。
