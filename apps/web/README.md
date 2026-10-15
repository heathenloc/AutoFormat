# AutoFormat 预览页面

第二步实现 TypeScript + PDF.js 页面，消费已发布任务的本地 API：版本浏览、报告摘要、PDF 翻页与缩放、单页文字选择、DOCX／Markdown 报告下载、反馈保存与接收凭据。

第三步增加服务端 PDF.js 文字层复核、同版本 DOCX 字符锚点、重复文字候选及目标确认。跨段、跨页和页眉页脚等目标须先确认；隐藏、修订、字段和绘图等不可靠结构会阻止定位。反馈仍不执行格式修改。历史版本只读；浏览不会切换工作起点。

第四步增加选中文字／所在段落／所有同类内容／全文四种范围，保存前确定性解析常见格式表达，并展示属性、值、对象类别、字符条件、实际最小作用单位及对象数量。保存后可逐项补齐缺失格式值、确认实际范围；原话和历史文件保持不变。无法理解的限制、范围不一致和目标歧义会保留为待核对项。详见 [第四步实现](../../docs/preview-feedback-parsing-step4.md)。

## 编辑前确认

连接配置了 intake 的完整 API 主机时，V0 页面展示选项式确认卡片。支持选择候选规则、提交场景、模板采用策略、常见值补充和“暂时忽略”。全部待确认项处理后，点击“开始格式编辑并生成初稿”；无问题的上传直接生成 V1。独立 preview_host 仍只服务既有预览，不承担上传或初稿发布。

## 构建

需要 Node.js 24 与 pnpm 11.25.0；依赖版本由 `pnpm-lock.yaml` 固定。

```powershell
cd E:\EasyFormat\apps\web
pnpm install --frozen-lockfile --ignore-scripts
pnpm build
cd E:\EasyFormat
dotnet build services/docx_engine/AutoFormat.DocxEditor
```

安装缓存写入项目 `runtime/`，构建产物在忽略的 `dist/`。工作线程、CMap、标准字体和 WASM 解码器全部本地提供，不依赖 CDN。

## 打开已有任务

在项目根目录运行，替换存储目录和任务 ID（首次处理响应的 `task_id`）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m autoformat.preview_host `
  --store E:\EasyFormat\runtime\my-store `
  --task <task_id> `
  --web-dist E:\EasyFormat\apps\web\dist
```

API 包须已安装在项目虚拟环境中，Node.js 24 与 .NET 10 在 PATH 中。启动器绑定随机回环端口并打开浏览器，Ctrl+C 退出。默认读取既有预览、接收反馈、只读定位并核对格式需求与范围；按 [第六步配置](../../docs/preview-feedback-editing-step6.md) 明确提供固定哈希的编辑器、LibreOffice 和字体环境后，可实际编辑、渲染并发布后续版本。独立预览宿主不承担上传、模型解析或初稿发布。定位组件缺失时仍可预览与保存反馈，界面会说明定位及范围核对不可用。自定义组件路径可用 `--node` 与 `--selection-dll`。未来桌面外壳可在 `bind_local_api(web_dist_dir=..., selection_indexes=...)` 后使用 `host.ui_url(task_id)` 启动同一页面。

页面启动后立即移除 URL fragment 中的会话字段；令牌仅保存在内存中，每个 API 请求通过专用请求头授权。浏览器整页刷新会丢失会话，需要从启动器重新打开；页面的“刷新版本”按钮保留会话。Vite 开发服务器可检查布局，实际任务通过同源 API 主机查看。

## 测试

第七步增加“反馈问题与进度”、待处理／已完成筛选、重开后的原选区与补充表单恢复、报告待处理证据，以及“从此版本继续修改”。历史浏览保持只读，明确继续后下一次实际编辑生成新子版本；后来的反馈例外不会带入更早的历史分支。首次忽略的学术要求目前仅展示报告明细。实现与边界见 [第七步记录](../../docs/preview-workspace-step7.md)。

已解析反馈下可点击“核对规则冲突”，查看旧规则、新需求和证据，并按实际范围选择保留、本处例外或更新规则。决定生成独立快照，尚不修改论文；来源不可核验、范围未确认及继承目标待重算均明确提示。响应丢失可重试同一选择。实现与边界见 [第五步记录](../../docs/preview-feedback-rules-step5.md)。

```powershell
pnpm exec playwright install chromium
pnpm test
```

默认浏览器夹具使用真实 DOCX、SQLite 和报告以及确定性的两页可选择 PDF。设置以下变量后使用已固定哈希的 LibreOffice 生成真实 PDF，并增加中文／跨行选择检查：

```powershell
$env:AUTOFORMAT_TEST_SOFFICE='E:\LibreOffice\26.8.0-admin\program\soffice.com'
$env:AUTOFORMAT_TEST_SOFFICE_SHA256='95016b59e08da1e6cbb02fc8f027593c076bf47df795092578afdd995306ac85'
pnpm test
```

歧义候选用独立的合成 PDF 夹具构造，真实中文跨段检查仍使用 LibreOffice PDF。第四步还检查连续补值、范围控件不一致、同类与字符过滤计数、未知限制、确认响应丢失以及迟到／错配的保存前解析。测试产物只写入 `runtime/browser-preview/`、`runtime/playwright-results/` 和 `runtime/preview-step*.png`。非 Windows 环境可用 `AUTOFORMAT_TEST_PYTHON` 指向对应的项目 Python。实现说明见第二至第四步文档。
