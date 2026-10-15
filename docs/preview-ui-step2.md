# 预览与用户编辑：第二步——PDF.js 页面

日期：2026-10-06。前置契约见 [`preview-feedback-contracts-step1.md`](preview-feedback-contracts-step1.md)。

> 本文记录第二步交付时的状态。2026-10-07 已接入保存后的可信定位与候选确认，当前功能和边界以 [第三步开发记录](preview-selection-step3.md) 为准。

## 当前功能

| 功能 | 行为 |
| --- | --- |
| 版本浏览 | 默认打开当前工作版本，显示版本号、创建时间、父版本与工作起点；点击历史版本只查看，不修改工作指针 |
| PDF 预览 | 校验实际 PDF SHA-256、版本／报告／预览身份和页数后显示；分页、页码跳转、40%–200% 缩放及适合宽度 |
| 文字选择 | PDF.js 文字层提供标准文字选择；保存当前页精确文字、前后文和原始 PDF item 索引，偏移采用 UTF-16 |
| 状态隔离 | 切换版本、翻页、缩放或实际容器宽度改变时清理旧选区；中止旧版本请求，忽略迟到结果 |
| 报告 | 显示选中版本实际完成状态、本轮修改数、待处理数与说明；无规则的报告明确显示未评估 |
| 下载 | 通过会话授权 fetch 获取选中版本 DOCX 和 Markdown 报告，再创建短期本地 Blob 下载；V0 只有原稿下载 |
| 反馈 | 工作起点的 V1+ 可保存带选区的反馈或全文咨询；原话不裁剪；保存后明确提示已接收、尚未编辑 |
| 重试 | 请求完成但响应丢失时保留原话和同一请求 ID，重试取得原凭据；不会产生重复反馈或论文版本 |
| 空态与错误 | 无会话、无版本、V0、加载／校验失败、过期工作版本、历史只读均有说明及可用操作 |

页面位于 `apps/web/`，固定 PDF.js 6.4.299、TypeScript 7.0.2、Vite 8.3.3，浏览器验证使用 Playwright 1.63.0。纯 TypeScript DOM 实现，文档文字、报告说明和反馈通过 `textContent`／输入控件显示，不作为 HTML 执行。

## 本地接入

`create_local_api()`／`bind_local_api()` 增加可选 `web_dist_dir`。固定 `/` 页面和 `/assets/` 资源不含任务内容，可在回环 Host 和 Origin 校验后读取；**所有 `/api/` 路由仍需会话头**。不开放 CORS，不提供服务器文件路径。启动器 `python -m autoformat.preview_host` 接收既有存储和任务 ID，以随机回环端口打开页面。

主机通过 `host.ui_url(task_id)` 的 URL fragment 传入启动会话；页面在首次 API 请求前移除 fragment，令牌仅在内存中，不写入 localStorage／sessionStorage，不打印启动 URL，不放入查询字符串或 API URL。固定 shell 与资源不回显令牌或任务数据。刷新版本保留内存会话；整页重新加载须由主机重新启动会话。同一标签页收到新启动 fragment 时重新初始化。最终 WebView2 外壳与安装包仍属后续步骤。

静态响应含 CSP、no-referrer、nosniff 和 no-store。PDF.js 工作线程、字体、CMap 与 WASM 全部来自本地包。只允许同源脚本／工作线程／连接；WASM 解码使用单独的 `wasm-unsafe-eval`，不开放 JavaScript eval。Windows 注册表可能把 `.mjs` 映射成 `text/plain`，本地静态适配器固定 JS／MJS／WASM MIME，保证模块线程在 nosniff 下仍能加载。

版本列表新增 `working_version_id`，用于当前版本反馈权限和历史浏览说明，不读取“任务最新规则”替换历史版本上下文。未配置编辑器的预览主机明确拒绝旧正文编辑路由。

## 当前边界

本阶段单次显示一页，可选择该页内单行或跨行文字；选区提示不等于定位成功，重复文字、DOCX 多对象／跨页映射与歧义处理由第三步实现。尚未增加“返回此版本继续修改”入口；历史反馈写入仍需后续工作起点切换功能。

反馈保存仍沿用第一步 `received` 协议，不创建 DOCX 锚点、格式规则、编辑计划或新论文版本。轻量解析、真实作用范围、冲突确认、实际编辑和问题闭环按后续步骤接入。全文输入也只是需求／咨询的记录，不代表用户已批准全文修改。

## 验证

API 检查覆盖公开 shell 的数据隔离、会话／Host／Origin、路径穿越、Windows MIME、历史不可变、工作指针和预览主机编辑禁用。浏览器检查覆盖实际 Canvas／文字层、鼠标选择、中文及跨行选择、页码范围、缩放清理、身份／PDF 哈希、迟到响应、历史报告、授权下载、丢失响应重试、会话引导和窄屏布局。真实渲染夹具的格式变化在重新读取 DOCX 后核对，测试数据位于忽略目录，不作为产品任务或格式合规样本。

验收：TypeScript 严格编译及 Vite 构建通过；真实 LibreOffice PDF 的浏览器检查 **11 passed**；AutoFormat 回归 **118 passed / 5 skipped**，既有跳过项为未配置显式渲染环境的测试。API 反馈与页面检查合计 **57 passed**。`git diff --check` 通过。运行方式见 [`apps/web/README.md`](../apps/web/README.md)。
