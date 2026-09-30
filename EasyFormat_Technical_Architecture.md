# EasyFormat 技术架构与开发实施文档

> 状态：已确认架构基线；可供后续 Codex 分阶段开发  
> 日期：2026-09-28；首次处理顺序修订：2026-10-01
> 依据：[产品需求文档](EasyFormat_PRD.md)、[Brief Parsing 解析侧设计](BriefParsing_EasyFormat.md)、本项目内的 [Brief Parsing 复制版](modules/brief_parsing/README.md) 及用户在架构讨论中确认的决策

## 0. 文档地位与开发边界

本文件确定 EasyFormat 从 Brief 解析、DOCX 编辑、预览反馈到历史版本的端到端实现方案。若较早的 PRD 或解析侧设计仍写着“预览、编辑器契约待定”，以本文件记录的**后续已确认决策**为准；未被本文件改变的产品范围继续按 PRD 执行。领域细节和样本验收继续参考解析侧设计。

**Brief Parsing 的开发副本已经建立在 `modules/brief_parsing/`。后续所有针对 Brief Parsing 的修改、测试、依赖调整均在此副本中进行；`E:\Brief Parsing` 原目录只可读取，不得修改、格式化、清理、提交或作为构建输出目录。** 副本是当前工作目录快照，包含来源目录当时的未提交改动；来源 Git HEAD、复制时间、文件清单与 SHA-256 见 [`modules/brief_parsing/SOURCE_SNAPSHOT.json`](modules/brief_parsing/SOURCE_SNAPSHOT.json)。这不是从来源 HEAD 创建的干净检出，也不是与来源目录实时同步的链接。

首版只复制解析代码、领域包、提示词、契约、评测、测试、开发脚本和项目元数据；未复制来源 `.git`、虚拟环境、运行产物、密钥、独立桌面 UI 或部署目录。EasyFormat 自行实现 UI 与部署。若以后需要吸收来源项目更新，应先比对快照和差异，在 EasyFormat 副本中显式移植并测试，禁止直接覆盖副本。

## 1. 已确认的产品和技术决策

| 事项 | 已确认方案 |
| --- | --- |
| 入口 | 同一任务上传学校 Brief／模板和论文 DOCX；解析与编辑在 EasyFormat 内连续完成 |
| 首次交付 | 首次只需上传上述两个文件；系统自动处理可靠、无冲突的格式要求并先发布可下载的 V1，目标是解决受支持格式问题的绝大部分；不以人工来源分类、逐项问答或预览选区为前置条件 |
| 原稿 | V0 是不可修改的原始 DOCX；每轮实际编辑生成独立文件，历史可分支回滚 |
| Brief 冲突 | 展示互斥要求和证据，由用户决定；先问冲突，再问未提及属性 |
| 模板版式 | “现有版式”只指 Brief 自带模板；未明确属性按页面、标题、正文等类别询问是否沿用；未确认不执行 |
| 编辑器 | 确定性程序修改 DOCX；不让生成式 AI 重写论文正文或操作文件 |
| 预览 | 首版允许少量与 Word 的排版差异，优先低成本／免费方案；渲染器必须可替换 |
| 标注 | 在预览中用光标选中文字并输入新需求；不实现圈画 |
| 反馈范围 | 默认只修改选中处；可选整个段落、所有同类内容、全文；提交前显示实际作用范围 |
| 新需求冲突 | 与已确认 Brief 规则冲突时暂停受影响修改并提醒；用户可保留原规则、设本处例外或更新规则 |
| 反馈解析 | 复用解析侧格式规则模型和校验能力，增加不调用完整 Brief 流水线的轻量入口；首版常见表达采用确定性解析，无法理解时请用户补充结构化信息 |
| 执行时机 | 清晰、定位可靠且无冲突的反馈提交后直接生成新版本；不确定、扩大范围或冲突时先确认 |
| 例外寿命 | 本处例外随当前版本的后代保留；从例外产生前的版本分支不带入；全局规则更新时重新检查 |
| 机械内容 | 可自动插入／更新能够从文档可靠推导的目录、页码、编号；不得编造图表来源、文献信息或学术正文 |

这里的“默认只修改选中处”只适用于**V1 发布后的预览反馈**，不是首次处理的输入要求。若属性只能作用于更大的 Word 结构，例如段落居中，界面必须在提交前把实际最小修改单位显示为“所在段落”，不能假称只改几个字。若用户输入写明“所有二级标题”，但范围控件仍是“仅选中处”，必须请用户统一两者，不能静默扩大或缩小范围。

## 2. 目标、范围与总体结构

P0 输入论文只支持 DOCX，输出可继续编辑的 DOCX、对应 Markdown 报告和可选中文字的预览。编辑范围沿用 PRD：页面基础设置、标题、正文、已有脚注／尾注、已有引用外观、目录、页码和表格。图片本身的尺寸、位置等不在 P0 自动编辑范围；相关 Brief 要求仍需识别、保存和报告。论文文字内容、引用内容和参考文献条目顺序不得被格式化操作改写。

```text
学校 Brief／模板 ──> 项目内 Brief Parsing 副本 ──> Requirement IR／证据
论文 DOCX(V0) ────> 结构扫描 ──────────────────────────────┤
                                                            v
                                        自动验证的安全规则 + 待处理问题
                                                            │
                                                            v
                                         修改计划 → DOCX 编辑与校验
                                                            │
                                                            v
                                          初稿 V1 + 报告 + 可选文字预览
                                                            │
                               ┌────────────────────────────┴───────────┐
                               v                                        v
                       下载／回答剩余问题                   预览选区 + 用户输入
                                                                        │
                                                                        v
                                                  轻量反馈解析 → 后续版本微调
```

内部保持三个边界：

1. **解析边界**回答“要求是什么、依据在哪里、是否冲突”，不修改论文。
2. **编辑边界**接收经过程序验证可安全执行或由用户确认的类型化规则、目标 DOCX 版本及作用范围，生成计划并修改副本，不直接理解原始自然语言。
3. **交互与版本边界**管理问题、用户决定、预览、下载和不可变历史；不把 PDF 当作论文主文件。

这些边界属于同一个 EasyFormat 产品和任务流程，P0 无须部署成三个独立网络服务。

## 3. 推荐技术栈与运行形态

| 层 | P0 方案 | 原因与替换边界 |
| --- | --- | --- |
| 工作流 API | Python 3.12 + FastAPI | 与项目内 Brief Parsing 副本同语言，便于复用其服务、模型和校验器；Windows 本地与后续 Web 使用同一 API |
| Brief 解析 | `modules/brief_parsing` 中的本地副本 | 保留现有安全接收、证据、模型隔离和 Parse Bundle；仅在副本开发论文领域能力 |
| DOCX 编辑核心 | C# / .NET 10 LTS + Open XML SDK | 对 DOCX 包和 WordprocessingML 作类型化、可测试的低层编辑；编辑核心以独立可执行程序接入，不绑定 Python UI |
| 编辑核心调用 | 子进程任务协议：输入 JSON manifest 与沙箱内文件路径，输出 JSON 结果；日志写 stderr | Windows 本地可直接运行；P1 后台作业可复用同一程序，调用方式可改为队列／容器而不改规则契约 |
| 元数据 | SQLite（P0）；Repository 接口预留 P1 数据库 | 保存任务、规则决策、问题和版本关系；文件内容单独存储 |
| 前端 | TypeScript + Web UI；PDF.js 文本层 | 同一界面可嵌入 Windows 窗口并迁移到网页；用户通过标准文字选择提交反馈 |
| Windows 外壳 | 本地 FastAPI + pywebview／WebView2，绑定 `127.0.0.1` 的随机端口 | 延续现有 Brief Parsing 桌面应用的轻量模式，但 EasyFormat 单独实现与打包 |
| P0 预览渲染 | LibreOffice 无界面转换 DOCX → PDF | 低成本；只作为可替换的 `PreviewRenderer` 适配器，不作为编辑核心 |
| 报告 | 版本化 JSON 事实源 + Markdown 渲染 | 程序可查、用户可读；网页视图后续复用 JSON |

具体 NuGet、前端和 LibreOffice 版本在实施时锁定并记录。预览字体集合、LibreOffice 版本与转换参数也属于版本元数据。.NET 10 是当前 LTS 选择；到实施时若其支持状态变化，应使用仍受支持的 LTS 并跑兼容测试。[.NET 支持周期](https://dotnet.microsoft.com/en-us/platform/support/policy) · [Open XML SDK](https://github.com/dotnet/Open-XML-SDK) · [LibreOffice 命令行](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html) · [PDF.js](https://github.com/mozilla/pdf.js/)

Open XML SDK 不提供 Word 同等的页面布局引擎，也不会仅因写入目录字段就算出可靠页码。目录／页码刷新必须是独立步骤；不能把 PDF 转换成功等同于下载 DOCX 的字段已刷新。Word 桌面自动化不得作为 P1 无人值守服务的唯一核心。[微软关于无人值守 Office 自动化的说明](https://learn.microsoft.com/en-us/office/client-developer/integration/considerations-unattended-automation-office-microsoft-365-for-unattended-rpa)

## 4. 代码目录与复制版维护

建议后续实施形成以下目录；目前只有文档、测试材料和 `modules/brief_parsing` 已存在，其余为目标结构：

```text
EasyFormat/
├─ AGENTS.md                          # Codex 开发边界
├─ EasyFormat_PRD.md
├─ BriefParsing_EasyFormat.md
├─ EasyFormat_Technical_Architecture.md
├─ modules/
│  └─ brief_parsing/                 # 已复制的 Python 项目；只修改本目录
│     └─ SOURCE_SNAPSHOT.json
├─ apps/
│  ├─ api/                           # EasyFormat Python 工作流、API、存储
│  └─ web/                           # TypeScript UI、PDF.js 预览
├─ services/
│  └─ docx_engine/                   # .NET Open XML 编辑和校验程序
├─ contracts/                       # 跨语言 JSON Schema、示例与版本策略
├─ tests/
│  ├─ fixtures/                      # 已获准的 DOCX、Brief 与预期结果
│  ├─ contract/
│  ├─ integration/
│  └─ e2e/
└─ runtime/                          # 运行文件；必须忽略或存于用户数据目录
```

复制版的 Python 项目原本为独立应用，`pyproject.toml` 中仍含其 API、评测等依赖。集成时可把它作为本地包安装；不要让 EasyFormat API 依赖来源目录的 `PYTHONPATH`，也不要将来源目录当作可编辑安装路径。保留上游通用测试，并在副本新增学术论文用例。来源目录当前带未提交改动，后续 Codex 不得假设 `source_git_head` 已包含快照全部内容。

## 5. 核心数据契约

契约文件放在 EasyFormat 顶层 `contracts/`，采用 JSON Schema，显式 `schema_version`。跨 Python、C# 和前端传递的 ID 应稳定、不含物理路径。未知属性和未来对象允许以版本化扩展承载，但编辑器不认识的属性只能报告 `unsupported`，不能猜测相近操作。

### 5.1 `AcademicFormatRuleSet/1.0`

它是 `Requirement IR` 的论文格式语义投影，保留源 Parse Bundle 和证据引用，不把通用 `ExecutionBrief` 强行当作 DOCX 操作指令。每条**原子规则**至少包含：

```text
rule_id, schema_version
source_kind: brief_explicit | template_observation_confirmed | user_feedback
source_artifact_id, source_version, evidence_refs, decision_id?
target: object_kind + semantic_role + selector
property: 注册表中的属性 ID
value: 原文值 + 规范值 + 单位 + 词典版本
character_scope: all | cjk | latin | digits | ...
condition: 提交版本／章节等可判定条件
requested_scope, effective_scope: selection | paragraph | same_kind | document
resolution_ref: 有覆盖或例外时指向用户决策；不得凭时间自动决定优先级
status: verified | pending_conflict | pending_condition | check_only | unsupported
```

例如“一级标题居中、小三、黑体加粗”拆成三条原子规则，共享同一证据。字号“小三”保留原文并规范为 15 pt；字体需区分东亚、拉丁和复杂文字脚本。目标和属性采用注册表，不把 P0 清单写死在语义 Schema 中。

Brief 明文要求可在证据、值、适用条件、冲突和目标范围均通过确定性校验后直接进入首次自动执行规则集，不要求用户先逐条标记“明确要求”。不能证明来源或定位的候选进入 V1 报告与后续问题队列。`template_observation` 在用户按类别确认前不进入有效规则集；论文初稿现有格式只是编辑器的“修改前值”，不能充当学校规则。格式规则快照是每个 DOCX 版本的依据，不得事后原地改写。

### 5.2 `FeedbackSubmission/1.0` 与 `FeedbackParseResult/1.0`

反馈提交至少包括 `task_id`、`base_version_id`、`preview_artifact_id`、用户原话、所选文本、PDF 页与文本层跨度、选区前后文、提交时的范围控件值、客户端请求 ID。选区位置是**定位提示**，不是自动确定的修改范围。

轻量解析结果需区分：`execution_defect`（已有规则未正确执行）、`new_rule`、`clarification_needed`、`question`、`out_of_scope`。若为新规则，输出与上节相同的类型化原子规则候选，以及可确定的属性／值／对象和缺失字段。若为执行缺陷，引用原规则与上轮验证项，不生成伪造的新格式规则。“这里还是宋体”必须先检查该处原本应遵守什么规则。

首版按受控词典和句式确定性解析常见属性；不启动完整 Brief 的提取器／审计器／条件解析器。用户可自由输入，无法可靠理解时显示已理解字段和缺失字段，让用户补齐。反馈处理默认不把论文正文或用户选中文字发送给 AI。将来如接入 AI，只替换此解析适配器；候选仍必须经过 Schema、证据、范围和冲突校验。

### 5.3 `SelectionAnchor/1.0`

锚点至少保存：`base_version_id`、`preview_artifact_id`、`renderer_id/version`、选中的确切文字、前后文、PDF 页及文本层索引／偏移、匹配到的 DOCX 对象 ID 和字符跨度、定位状态。DOCX 对象 ID 是 EasyFormat 结构索引的版本内稳定 ID，不假定 Word 原生段落自带永久 ID。

匹配时优先结构索引 + 文本 + 上下文联合定位；PDF 坐标和页码只能辅助。重复文本、跨段／跨表格、隐藏文字、页眉页脚、字体导致的文字顺序变化等须进入 `ambiguous`，让用户选择目标。提交后如果基础版本已变化，需重新定位并显示差异，不能把旧 PDF 坐标直接应用到新 DOCX。

### 5.4 `EditPlan/1.0`、`VersionNode/1.0`

`EditPlan` 记录基础版本哈希、有效规则快照 ID、每个操作的目标 ID、属性、前值、目标值、实际作用范围、前置条件、依赖对象、预计影响数量和执行状态。用户可以看到将影响哪里；后端再次验证范围和基版本，防止前端状态过期。

`VersionNode` 至少包含版本 ID、父版本 ID、DOCX 哈希与路径、规则快照、Brief／模板／用户决策版本、修改计划和验证报告、预览 artifact ID、渲染器及字体版本、创建时间。V0 无父版本，后续版本构成有向树；从历史版本继续编辑创建新子节点。仅咨询、跳过或暂缓而未实际改动的回答进入决策日志，不生成冗余 DOCX 版本；PRD 要求的首次 V1 即使没有可执行修改也要生成。

### 5.5 跨模块状态与错误码

API、报告和 UI 复用相同的机器状态：`needs_user_input`、`blocked_conflict`、`ambiguous_target`、`unsupported_property`、`field_refresh_pending`、`validation_failed`、`render_failed`、`ready`。每项状态带受影响的规则／对象 ID、可理解的中文原因和下一步动作；局部失败不能被任务级 `ready` 掩盖。新增状态采用版本化枚举，不依赖前端解析自由文本错误消息。

## 6. Brief Parsing 副本的开发任务

1. 在复制版中把 `academic_paper.example` 扩展为正式 `academic_paper` Domain Pack。覆盖页面、正文、标题、目录、页码、脚注／尾注、引用、表格和可报告但暂不编辑的对象。
2. 为 DOCX 模板增加只读结构／版式观察：节、纸张、页边距、样式继承、直接格式、表格边框、页眉页脚和字段等。每个观察值带来源和定位，不能冒充 Brief 文字要求。
3. 增加区域角色、中文字号和单位词典、字符脚本范围、条件表达，以及“示例／背景／明确要求／模板观察”的区分。
4. 将冲突检测改成“目标与条件交集 + 同属性 + 不兼容值”的判断。目录三级与正文四级应同时成立；不同提交版本的要求应是条件分支。
5. 保留通用 `Requirement IR` 为解析事实源；新增任务标识 `format_academic_paper` 的 `AcademicFormatCompiler`，把自动验证的明文要求和后续经用户决定的条目编译为 `AcademicFormatRuleSet`。编译器是项目内副本的新增能力，输出契约由 EasyFormat 顶层 `contracts/` 管理。
6. 现有 `BriefParserService` 要求至少一个 task type，通用 `ExecutionBrief` 面向其他任务。为 EasyFormat 增加**向后兼容的 parse-only 路径**：先生成 Parse Bundle，再调用论文格式编译器；不以通用 `ExecutionBrief` 的自由 JSON 字段承载全部编辑语义。旧任务类型及其契约继续通过原有测试。
7. 首稿 V1 发布后，问题队列先展示冲突及来源不一致项；待用户处理后，才按类别询问未明确属性是否沿用 Brief 自带模板。未答、跳过或暂缓均不产生默认规则，且不阻断独立可靠规则的首次执行。

复制版的 `Requirement IR v1` 当前只有通用 `subject/value/scope`，来源类型也不足以直接表达预览反馈；新增论文格式投影和反馈 envelope，不要把 PDF 选区、版本号硬塞进通用证据字段。当前冲突检测和编译器注册仍需按上面的目标调整。详细缺口见 [解析侧设计](BriefParsing_EasyFormat.md)。

## 7. DOCX 编辑核心

### 7.1 结构索引与能力声明

引擎先对论文 DOCX 建立语义树：文档／节／段落／文字片段／表格／单元格／脚注／尾注／字段，并记录标题、目录、引用等候选角色、识别依据和状态。角色优先由 Word 样式、编号、字段和位置确定；无样式标题可用确定性规则识别高置信候选，模糊项暂停。首版不让 AI 判断论文结构。

引擎按对象和属性公开能力表：`edit_and_verify`、`check_only`、`unsupported`。解析器保留全部要求；适配层按能力决定执行状态，不能静默丢弃。新对象、操作和验证器通过独立处理器注册。

### 7.2 修改计划与执行

首次根据已自动验证的 Brief 明文规则计算有效规则快照；后续再结合用户确认的冲突决定、模板规则和反馈例外计算新快照。冲突不是简单“新规则永远覆盖旧规则”：只有用户明确选择的本处例外或全局规则更新，才成为决策记录；未决冲突只阻断相交的目标和属性。清晰独立的规则继续执行。

操作按页面／分节、样式和角色、局部直接格式、表格／注释、目录与页码字段等依赖顺序规划。全局同类修改优先调整或创建合适样式；但若样式被非目标内容共用，须复制样式或用局部格式，不能让“所有二级标题”误改其他段落。本处例外用局部操作；对段落级属性先把选区提升到所在段落并展示。只改命中的属性，保留其他直接格式、链接、书签、批注、图片和文本。

每个操作带前置条件与幂等键。相同规则重复应用不应增加无关 XML 改动；同一属性不能被后续操作无提示覆盖。编辑始终针对父版本副本进行；失败只影响当前候选，不覆盖父文件。目录、页码、编号只能从可靠结构生成，缺失来源或映射不完整时暂停受影响操作。

### 7.3 字段刷新

`FieldRefreshProvider` 与 `DocxEditor` 分离。编辑器先写入可更新的字段与样式；刷新器可在**临时副本**上尝试由排版引擎更新目录／页码，再重新读取、比较正文和非目标结构。若成功且验证通过，采用刷新副本；若刷新会改坏正文或无法验证，则保留编辑器结果，并把字段状态标为 `pending_manual_check`，不得报告“已完全通过”。预览 PDF 中显示的页码不能单独证明下载 DOCX 的缓存已更新。

## 8. 预览、选区和渲染器替换

`PreviewRenderer` 输入不可变 DOCX 文件及字体配置，输出 PDF、可选文本索引、页数、渲染器名称／版本与诊断信息。P0 用 LibreOffice headless 生成 PDF；前端使用 PDF.js 的文本层显示并选中文字。必须先检查 PDF 可选择／复制文字；纯图片式预览不能满足反馈入口。

预览与编辑属于不同组件。渲染器未来可换成更高精度实现，前端仍只接收标准 PDF 和锚点元数据。每个历史预览保存其自身渲染器版本；重新渲染同一 DOCX 会生成新 preview artifact，不覆盖旧 PDF，也不改变 DOCX 版本。旧反馈仍关联原 PDF 和已保存的语义锚点，必要时对新预览重新匹配。

预览允许与 Word 有少量分页和位置误差，因此用户界面不得声明“与 Word 完全一致”。差异最大的样本（复杂表格、跨页脚注、字体缺失）要进入渲染回归集，并在报告中保留人工复核状态。P0 可要求用户安装 LibreOffice；启动时检查可执行文件、字体和版本，未满足时给出明确诊断。P1 可将渲染器封装到隔离的后台容器。

## 9. 用户流程与状态机

### 9.1 首次处理

1. 用户首次只上传 Brief／模板和论文 DOCX；安全检查后保存不可变 V0，不要求预览选区、自由文本修改指令或逐项确认。
2. 运行项目内 Brief Parsing 副本，生成 Parse Bundle 与论文格式候选规则；整体解析失败则停止格式编辑并给出诊断，局部不确定不阻断其他规则。
3. 建立论文结构索引。确定性程序核对 Brief 明文证据、值、冲突、适用条件、编辑能力和目标定位；只把可靠、无冲突的类型化规则送入首次修改计划。模板观察和不确定项留待处理。
4. 自动执行可安全完成的项目并校验，生成可下载的初稿 V1、Markdown 报告和 PDF 预览。产品验收目标是解决受支持格式问题的绝大部分；若当前样本没有可执行项，仍生成未改动副本并明确说明，不得伪称已完成格式修改。
5. V1 发布后才展示剩余问题与预览微调入口。问题先处理 Brief 冲突，再询问未明确属性是否沿用模板。用户可先下载 V1，再回答问题或在 V1 预览中选中文字提出新需求。

### 9.2 预览反馈

本节只处理 V1 或后续版本的微调，不参与首次自动生成 V1。

1. 前端提交原话、选区及基础版本；后端将选区定位到同版本 DOCX。
2. 轻量入口识别“执行缺陷／新规则／不清楚／超范围”，并输出类型化候选。
3. 显示默认范围和实际最小修改单位。清晰本地修改直接执行；多处匹配、表达不清、范围扩大或与已确认规则冲突时暂停并请用户决定。
4. 决策后只重新规划受影响的对象及其依赖（例如标题变化引起目录刷新）；不重新解析整份学校 Brief。
5. 成功后生成新 DOCX、报告与预览。反馈保留在原预览版本上，下一轮使用新预览。

### 9.3 回滚与分支

“返回此版本继续修改”只更换工作起点，不删除后代。新版本的父节点是所选历史版本；它继承该版本当时的有效规则快照和已存在例外。局部例外在子版本中按语义锚点重新定位；若原文字或结构变化导致定位不唯一，该例外转为待确认，不能静默套到别处。后续更新 Brief 或全局规则时，重新校验继承的局部例外。历史文件、报告、反馈、决定和预览只读。

## 10. 存储、事务和 API

P0 元数据建议由 SQLite 管理；DOCX、PDF、JSON 和 Markdown 按 `task_id/version_id/artifact_id` 存入应用数据目录，数据库保存相对路径、哈希、大小、状态与关系。任务与版本 ID 用不可猜的随机标识；文件下载经 API 授权／校验，不暴露机器绝对路径。

推荐 API 边界如下，具体请求和响应须用顶层 `contracts/` 的 Schema 固定：

| 方法与路径示例 | 用途 |
| --- | --- |
| `POST /api/tasks`、`GET /api/tasks/{task_id}` | 上传 Brief 与 DOCX，读取阶段状态和当前工作起点 |
| `GET /api/tasks/{task_id}/questions`、`POST /api/tasks/{task_id}/decisions` | 按规定顺序处理冲突、模板版式沿用及后续歧义 |
| `GET /api/tasks/{task_id}/versions`、`POST /api/tasks/{task_id}/versions/{version_id}/continue` | 查看分支，选择历史版本作为工作起点 |
| `GET /api/tasks/{task_id}/versions/{version_id}/artifacts/{kind}` | 获取 DOCX、报告或预览；`kind` 只允许登记过的 artifact 类型 |
| `POST /api/tasks/{task_id}/versions/{version_id}/feedback` | 提交选区、原话和范围，返回执行结果或待确认项 |

写请求带幂等请求 ID 和期望的基础版本哈希；陈旧请求返回明确的重定位／重试状态，不能悄悄写入新版本。

`POST /api/tasks` 的成功响应必须指向已发布的初稿 V1 及其真实格式完成状态；任务 ID、请求 ID 和模型处理告知属于协议与界面元数据，不要求用户额外提供选区或修改指令。当前代码已经能先发布 V1 基线副本，但自动规则计划和足够广的编辑器能力尚未完成，不能把“V1 可下载”当作“绝大部分格式已修改”的验收通过。

后台任务状态至少有 `queued → parsing → planning → editing → validating → rendering → ready`，失败时保存阶段与可理解的错误。版本发布需 DOCX、报告和预览均生成且通过各自最低校验；先在暂存目录写入并核对哈希，再以原子方式进入正式 artifact 目录，最后提交元数据。文件系统与 SQLite 无单一事务，启动时要清理未发布暂存文件并检查数据库所指 artifact 是否存在。字段刷新失败可作为显式待人工检查状态；DOCX 损坏或预览完全不可用不能伪装成成功版本。

P1 将存储仓库替换为具备用户隔离、加密、保留／删除能力的数据库和对象存储；上述业务契约保持不变。

## 11. 验证、错误处理与报告

每轮至少执行四层验证：

1. **包结构**：重新打开 DOCX，校验 Open XML 结构与必要关系；不能把 SDK Schema 校验等同于 Word 页面正确。
2. **内容保护**：比较正文、表格、注释、引用等规范化文本与非目标部件；获准的目录／字段生成记录为可解释的差异。原稿 V0 哈希始终不变。
3. **规则符合**：重新读取命中对象的**实际生效属性**，考虑样式继承和直接格式；逐条区分已满足、修改且通过、未执行、失败、待人工检查。
4. **渲染与选区**：PDF 可打开、页数合理、文字可选择，锚点可在 DOCX 中唯一匹配；排版异常样本进入人工复核。

报告同时列出本轮操作与累计状态，每条规则能回到 Brief 原文或用户反馈，标出影响位置、前后值、用户决定、失败原因和未处理项目。用户反馈原话与规范化规则都要保留，不能用后者覆盖前者。校验失败只发布安全的局部结果；若输出完整性不能保证，不发布该候选版本。日志只记录任务、规则和错误元数据，不记录论文全文、API Key 或选区正文。

## 12. 安全与部署约束

- Brief 解析沿用副本中的文件安全检查、资源限制和证据校验；论文 DOCX 也要检查文件类型、压缩包异常、外部关系、宏／受保护状态和大小限制。
- 解析阶段如调用云端 AI，仅发送 Brief 解析所必需的数据；论文正文及预览反馈不进入模型调用。用户须知悉 Brief 可能被发送到所配置的模型服务。
- 本地 API 仅绑定回环地址、随机端口，并对写接口采用会话令牌和来源校验；不可让其他网站随意驱动本地文件服务。
- 子进程只可读取本任务暂存目录内的输入，输出写入指定暂存目录；限制运行时间、并发与文件大小。LibreOffice 使用隔离的用户配置目录，转换用户文件时避免共享进程状态。
- 密钥由环境或受保护配置读取，不复制到 `modules/brief_parsing`、DOCX、报告或打包资源。运行数据与构建产物不得进入源码快照。

## 13. 测试与验收

### 13.1 样本集

使用 `TestDocuments/材料学院毕业论文模板2026.docx` 建立**解析**黄金样本；另外创建获准使用的论文测试 DOCX，覆盖规范样式、无样式标题、中西文混排、脚注／尾注、表格、自动／手工目录、分节页码、重复选中文字、跨段选择和损坏文件。模板不是论文初稿，不可直接充当“编辑成功”的唯一测试。

### 13.2 必过测试

- Brief 来源分类、字号换算、证据、冲突顺序、模板观察确认和 `AcademicFormatRuleSet` 契约测试；复制版原有通用测试继续通过。
- C# 与 Python 对同一 JSON Schema 的跨语言契约测试；未知规则被保留并报告为不支持。
- 编辑操作的幂等性、样式污染防护、局部例外、同类范围、正文内容保护、表格及注释保留。
- 目录／页码刷新：成功后验证；失败、映射不全或回写改变正文时标记待检查，不虚报成功。
- PDF 选区到 DOCX 的唯一定位；重复文本、跨段、渲染器变更和基础版本过期时不得误改。
- 首次只上传 Brief 与论文 DOCX，不传预览选区或微调文字；V0 不变、V1 在问答前可下载，报告列出实际自动修改数和待处理数，并用代表性样本核算受支持格式问题的首次解决率；有修改才追加后续版本、分支回滚、故障注入后无半成品可见、应用重启可恢复。
- 预览文字可选择、反馈冲突提醒、实际作用范围提示、Markdown 报告与文件对应。

PDF 与 Word 的允许差异目前是定性产品要求；在 P0 集成验收时，用同一字体环境下的 Word 导出参考 PDF 对代表性样本做人工比对，记录差异类型，再确定是否需要数值化阈值。不能在没有样本的情况下宣称“分页一致”。

## 14. 推荐开发顺序与每阶段完成标准

| 阶段 | 任务 | 完成标准 |
| --- | --- | --- |
| 0：基线 | 使用已复制的 `modules/brief_parsing`，核对来源快照；建立 EasyFormat 仓库、忽略规则和跨语言契约目录 | 原目录保持不变，副本可运行现有测试 |
| 1：关键验证 | 做 DOCX→PDF 可选文字、PDF 选区→DOCX 对象定位的真实样本原型；测试目录字段刷新回写 | 明确可定位场景、歧义处理和失败状态，不以静态截图代替 |
| 2：解析域 | 正式论文 Domain Pack、模板观察、范围冲突、用户决定、类型化格式规则编译器 | 当前模板黄金样本与通用回归测试通过 |
| 3：编辑内核 | .NET 结构索引、能力表、修改计划、核心操作与验证 | PRD P0 范围逐项有可执行或明确不支持结果，原文保护通过 |
| 4：工作流 | Python 任务／版本／报告／存储与 .NET 子进程调用 | 仅上传两个文件即可先自动产生有实际格式修改的 V1；代表性样本的首次解决率达到 PRD 目标，并通过多轮修改、失败恢复和分支回滚端到端测试 |
| 5：预览反馈 | LibreOffice 渲染器、PDF.js 选择、轻量反馈解析、冲突／例外交互 | 重复反馈、跨版本反馈及渲染器替换测试通过 |
| 6：交付 | Windows 打包、样本回归、资源限制与安装诊断 | 无需启动独立 Brief Parsing 应用即可走完整路径 |

后续 Codex 开发按一个阶段或一个可验收能力增量提交。每次修改先看本文件、PRD 和复制版 `SOURCE_SNAPSHOT.json`；只在 EasyFormat 目录下编辑。实现与本文件不同时，应在项目内记录技术决策及原因，再继续下一阶段。

## 15. 尚需在实施中量化的参数

文件大小／页数上限、单任务最大版本数、处理时长目标、可接受的预览差异阈值、Windows 安装包是否捆绑 LibreOffice，以及 P1 文件保留期和存储配额尚无用户给定数值。实现时先用可配置限制与可见诊断，不把任意开发默认值写成学校要求或产品承诺。选择具体阈值前用代表性论文样本和资源数据评估。

## 16. 主要技术依据

- [Microsoft：WordprocessingML 文档结构](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document)
- [Microsoft：Open XML SDK 入门](https://learn.microsoft.com/en-us/office/open-xml/getting-started)
- [Microsoft：Open XML 文档校验](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document)
- [Microsoft：无人值守 Office 自动化限制](https://learn.microsoft.com/en-us/office/client-developer/integration/considerations-unattended-automation-office-microsoft-365-for-unattended-rpa)
- [LibreOffice：命令行与无界面转换](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)
- [Mozilla：PDF.js 项目与浏览器预览](https://github.com/mozilla/pdf.js/)
