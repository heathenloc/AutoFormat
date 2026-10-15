# 编辑核心初版：属性覆盖、执行与验收

日期：2026-10-04。依据现行技术架构与本轮“覆盖当前 Brief Parsing 输出”的开发要求。

本轮新增 .NET/Open XML 编辑核心，保留旧单段／批量对齐命令。Python 入口从原始 Parse Bundle 重放 `AcademicDecisionSnapshot/1.0` 后，才将类型化有效规则和完整分片交给编辑器。配置了真实 `DotnetEditor` 的本地 API 已接入首次自动编辑 V1；只配置解析器的开发宿主继续发布明确标注未修改的基线副本。

## 1. 当前属性覆盖

当前解析决策校验器注册的 **35 个类型化格式属性**都有编辑处理器、保存后校验和正向 DOCX 回归。`capabilities` 命令声明属性、最小作用单位和验证方式。跨语言测试将此清单与复制版的 `ENUMS / BOOLEANS / LENGTHS / INTEGERS` 等注册项逐项比较；新增解析属性而未增加编辑能力会使测试失败。

| 类别 | 属性 ID | 数量 |
| --- | --- | --- |
| 字符 | `font.family`、`font.size`、`font.bold`、`font.italic` | 4 |
| 段落 | `paragraph.alignment`、`spacing_before`、`spacing_after`、`line_spacing`、`first_line_indent`、`hanging_indent`、`left_indent`、`right_indent`、`keep_with_next`、`keep_together`、`page_break_before`、`snap_to_grid`，均带 `paragraph.` 前缀 | 12 |
| 页面 | `page.paper_size`、`page.dimensions`、`page.orientation`，以及 `page.margin.all/top/bottom/left/right/header_distance/footer_distance/gutter` | 11 |
| 分节 | `section.column_count`、`section.text_direction` | 2 |
| 页码 | `page_number.number_format`、`page_number.start` | 2 |
| 目录 | `toc.max_depth` | 1 |
| 表格 | `table.border_style`：三线表、全框线、无边框 | 1 |
| 结构位置 | `caption.position`、`document.position` | 2 |

这里的“覆盖”指每个已注册属性具备处理与验证路径，不表示任意论文的对象都能自动定位。当前解析器另有未类型化的模板原始边框字典、参考文献著录样式、图片等仅报告项目；它们保持 `report_only / check_only / unsupported`，不从报告值猜测编辑动作。未确认模板观察、条件、区间和原始自然语言均不获得执行权限。

对象识别覆盖各级 Word 标题和样式继承、由章节确定的正文区域、摘要／关键词、目录及目录级别、参考文献、致谢、附录、表内段落、现有脚注／尾注、页眉／页脚和 PAGE 字段缓存。`Normal` 只在可靠区域上下文内成为正文；未标记首行保留为可能表头的 `table_cell`。引用段落按样式识别；原生 CITATION 字段及能与现有文献编号核对的单 run 数字引用可只调整引用字符。题注只在唯一相邻图／表和无分节跨越时移动。按本轮完整属性覆盖要求，可靠图题的文字格式与相邻位置纳入执行，图片内容、尺寸和位置仍保持原样。

## 2. 输入与输出

- `academic-edit-manifest/1.0`：父版本及 DOCX 哈希、任务内输入／输出文件名、规则快照哈希、完整有效规则与分片。
- `academic-edit-result/1.0`：每条规则的结果、每个操作的对象、部件、XML 路径、字符／侧边范围、前后值、实际最小作用单位、是否真的改动，以及内容／包／字段缓存的校验状态。
- Python `AcademicEditor.execute()`：重放源 Bundle 和决定，校验跨语言 Schema、固定编辑器二进制哈希、子进程超时、结果绑定和实际文件哈希。`plan_only=True` 输出计划，不写 DOCX。

对应 Schema 放在顶层 `contracts/` 与 API 包的 `schemas/` 中，由 `scripts/export_editor_schemas.py` 同步导出。旧契约不改写。

内部 CLI 示例，必须从已验证的可信工作流生成 manifest：

```powershell
dotnet build services/docx_engine/AutoFormat.DocxEditor --locked-mode
dotnet services/docx_engine/AutoFormat.DocxEditor/bin/Debug/net10.0/AutoFormat.DocxEditor.dll capabilities
dotnet services/docx_engine/AutoFormat.DocxEditor/bin/Debug/net10.0/AutoFormat.DocxEditor.dll inspect-academic runtime/example/parent.docx
dotnet services/docx_engine/AutoFormat.DocxEditor/bin/Debug/net10.0/AutoFormat.DocxEditor.dll plan-academic runtime/example runtime/example/academic-plan-manifest.json
dotnet services/docx_engine/AutoFormat.DocxEditor/bin/Debug/net10.0/AutoFormat.DocxEditor.dll apply-academic runtime/example runtime/example/academic-edit-manifest.json
```

CLI 是内部执行边界，不替代 Python 对 Brief 证据和用户决定的重放校验。HTTP 不接受客户端提交规则或 manifest。

## 3. 执行与验证

章节、区域、对象语言、表格序号、字符与页边距侧边的 include/exclude 范围均保留；未知轴和未绑定提交场景明确待处理。仅执行无冲突 `verified` 分片，未决交集继续报告。模型和用户原话不进入 XML 操作。

对每个可靠目标使用局部格式，保留共用样式。中文／西文／数字／复杂文字分别处理字体槽；必要时拆分纯文字 run，保留精确文本及链接容器。段落读取考虑直接格式、样式链和文档默认值；粗体与斜体区分样式 toggle 和直接值。表格或列表的条件继承无法证明时，需要直接属性来建立校验依据。会被继承的字符／行单位或悬挂缩进覆盖的物理长度保守待处理，避免写入一个不会生效的数值。

执行前复核相同 Word 属性、互斥首行／悬挂缩进，以及纸张、实际尺寸、方向与页边距组合。方向同时核对物理宽高，缺失或不一致的标记不会导致错误交换。无法同时满足时只阻断受影响目标，其他可靠操作继续；隐藏、修订、锁定容器、复杂合并表格等不确定目标也单独保留。直接或继承的非零单元格间距不能形成连续三线边框时，保留为待处理。

编辑只写暂存副本。保存后重新打开，使用 Open XML SDK 验证包结构，比较正文、表格、注释及其他文字，核对链接、书签、批注标记、图片与合并网格等非目标结构，再按输出路径读取实际属性。原稿哈希再次核对，结果通过才原子发布；既有输出不覆盖。已满足操作输出父文件的精确字节，重复执行不制造格式变化。

表格三线边框同时设置上下外边及表头分界线两侧的单元格边框，避免 `nil` 消除另一侧的横线；段距／缩进不通过写入零字符／零行单位来覆盖物理长度。依据：[微软段落缩进说明](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.indentation?view=openxml-3.0.1)、[微软表格边框冲突说明](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/7c791c5d-44c3-4fe8-abdd-8f136761bb93)、[Open XML 包验证](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document)。XML 验证不证明 Word 分页或字体安装情况。

## 4. 目录、页码与已知边界

已有复杂 TOC 字段和简单字段可调整大纲级数。手工目录只有在逐条目录标题与请求深度内的论文标题唯一、完整、顺序一致且边界可靠时才转换；保留原缓存文字，插入可更新字段。混合条目来源、跨分节、不完整标题映射或未知目录范围不转换。

目录与页码的字段定义可验证，但**下载 DOCX 的目录页码缓存尚未接入排版引擎刷新与回写验证**。它们始终保留 `pending_manual_check`，包括重复执行时；`changed` 单独表明定义是否实际修改。PDF 预览不能替代该校验。真实字体、分页和复杂表格外观仍需单独的渲染验收，本轮未宣称 Word 页面一致或真实论文首次解决率。

正文专用分栏／方向仅作用于已证明属于正文的整个节；与前置或其他区域共用一节时先报告，尚不自动拆分节。共用页眉页脚的局部章节范围、复杂编号推断、需要隔离样式的单位冲突、未注册对象和不可唯一定位的引用继续待处理。决策快照可交给 `execute()` 生成后续候选；问答 API 自动发布后续论文版本、预览选区微调和例外继承仍属于后续工作流阶段。

## 5. 本轮验收

```powershell
dotnet restore tests/AcademicEditor.Checks --locked-mode
dotnet run --project tests/AcademicEditor.Checks --no-restore
dotnet run --project tests/DocxEditor.Checks --no-restore
dotnet run --project tests/DocxIndex.Checks --no-restore -- TestDocuments/材料学院毕业论文模板2026.docx
./.venv/Scripts/python.exe -m pytest tests -q --basetemp runtime/pytest-autoformat-core
cd modules/brief_parsing
../../.venv/Scripts/python.exe -m pytest -q --ignore=tests/contract/test_infrastructure_baseline.py --basetemp E:/EasyFormat/runtime/pytest-brief-parsing-core
```

验收结果：编辑核心 **243 项检查通过，覆盖全部 35 属性**；AutoFormat Python **61 passed / 5 skipped**；复制版解析器 **391 passed / 2 skipped**。原单段／批量编辑与索引回归继续通过。

新核心检查各类目标、字号与间距单位、字符拆分、内容保护、幂等性、目录与页码字段、手工目录转换、局部冲突、隐藏目标隔离、相同单位等价、组合页面冲突和不可覆盖历史。Python 集成验证真实 Brief 到规则快照再到 .NET、决定重放防篡改、只读计划、JSON／Markdown 报告和问答前实际修改 V1。

复制版回归按原 README 排除 4 个依赖未复制部署文件的测试，不修改或补造来源部署文件。Windows 的 Linux 隔离测试及未配置真实外部组件的测试按原条件跳过；这些不计为真实渲染验收。所有产物写入本项目忽略目录，没有修改 `E:\Brief Parsing`。
