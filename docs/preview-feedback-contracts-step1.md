# 预览与用户编辑：第一步——反馈与版本契约

日期：2026-10-06。依据现行技术架构第 5、8–11 节，实施八步计划中的第一步。

本阶段建立版本化数据模型、反馈接收与持久化、跨记录校验。用户反馈只能关联已发布的 V1 或后续版本；论文、报告和 PDF 均保持原样。PDF.js 页面、实际定位、轻量解析、冲突编译和新 DOCX 发布分别在后续步骤实现。

## 1. 当前已经实现

- 严格、不可赋值的数据模型；拒绝未知字段和错误类型，保留用户原话及选区文字中的空格、换行。
- 反馈上下文从指定版本的不可变引用及可信文件生成，记录 DOCX、PDF、预览元数据哈希、渲染器及版本、页数、Brief 与规则快照 ID。**不读取任务最新解析规则指针来替换历史版本依据。**
- SQLite 追加式接收记录；同任务、同请求 ID、同完整输入返回原记录，不同输入返回冲突。新提交在同一事务内核对当前工作起点和文件状态。
- 历史反馈按任务与基础版本隔离，重启可读取；读取时核对内容哈希、数据库身份列及版本绑定。原话和选区保存在反馈记录中，不写入日志或错误响应。
- 提交只返回 `received / pending_feedback_processing`，HTTP 202，不调用解析器、定位器、模型、编辑器或渲染器，不生成 DOCX 版本。
- 提供后续适配器可调用的跨记录校验函数；确认须指向同一反馈、同一处理结果和实际列出的目标、范围或冲突。补充答案不能改写未声明缺失的字段。

代码：[`feedback_contracts.py`](../apps/api/src/autoformat/feedback_contracts.py)、[`feedback_store.py`](../apps/api/src/autoformat/feedback_store.py)、[`feedback_validation.py`](../apps/api/src/autoformat/feedback_validation.py)。

## 2. 契约与信任边界

| 契约 | 输入或输出 | 用途 |
| --- | --- | --- |
| `feedback-version-context/1.0` | 服务端输出 | 绑定一个已发布版本、预览及当时的规则依据，`context_id` 为规范化内容哈希 |
| `feedback-submission/1.0` | 客户端输入 | 原话、版本与预览身份、范围控件、PDF.js 文字层提示、请求 ID |
| `selection-anchor/1.1` | 后续定位器输出 | 绑定确切选区与 DOCX 对象 ID、字符跨度；保留原 `1.0` 原型契约 |
| `selection-resolution/1.0` | 后续定位器输出 | 唯一锚点，或歧义候选、过期与不支持状态 |
| `feedback-parse-result/1.0` | 后续轻量解析器输出 | 新规则、执行缺陷、补充信息、咨询、范围外；完整候选与已理解的部分字段分别保存 |
| `feedback-confirmation-request/1.0` | 后续交互输入 | 选择列出的目标、确认实际范围、补充注册的属性值；绑定处理结果哈希 |
| `feedback-decision-request/1.0` | 后续交互输入 | 针对列出的冲突选择保留原规则、本处例外或更新规则 |
| `feedback-rule-snapshot/1.0` | 后续受信任编译器输出 | 父快照、规则来源、决定引用、例外产生版本和锚点；预留分支继承语义 |
| `feedback-record/1.0`、`feedback-receipt/1.0` | 服务端输出 | 保存原始提交及其哈希，返回可重放的接收凭据 |

所有 Schema 自包含，位于顶层 `contracts/` 与 API 包 `schemas/`，通过 `scripts/export_feedback_schemas.py` 同步。示例见 [`example-selection.json`](../contracts/feedback-submission/example-selection.json) 和对应的 [`example.json`](../contracts/feedback-version-context/example.json)。示例 ID 和哈希是演示值，不属于真实任务。

**Schema 通过、内容哈希正确或输出记录写着 `verified`，都不授予编辑权限。** 本阶段没有客户端上传规则、锚点、manifest 或规则快照的入口。后续编译器必须从可信存储重放原话解析、目标定位、范围审查和用户决定，再核对学校规则冲突及编辑器实际能力，才可生成计划。哈希是完整性校验值，不是签名，也不替代来源重放。

`seal_contract()` 在嵌套默认字段规范化后生成内容哈希，再运行最终模型的全部验证；适配器应使用它生成带哈希的服务端输出。客户端确认请求只携带从服务端读取的结果／候选 ID。

格式候选复用本项目解析副本的注册属性、值、单位、角色和范围校验器，不运行完整 Brief 流水线。未知属性、错单位、非有限值不成为完整候选；无法理解的输入通过补充信息结果表达。执行缺陷必须引用已有规则，不创建伪造的新规则。

## 3. 选区与实际范围

选区提示保存精确文字、前后文及一个或多个 PDF 文字层跨度。偏移明确采用 **UTF-16 code units**，与 JavaScript 和 .NET 对齐；例如 `字😀` 长度是 3，不是 Python `len()` 的 2。跨度要有序、不重叠、页码在预览范围内。

锚点 `1.1` 使用对象 ID 和字符范围列表，支持契约上表示跨行、跨页或多对象选择，不暴露 XML 路径。**这不表示当前定位器已经能处理这些选择。** 原 `AnchorLocator` 与 `verify_pdf_selection` 的保守行为不变；第 3 步须实际验证并产出新锚点，不能把收到 PDF 提示当作定位成功。

`requested_scope` 是控件值；`ScopeReview.effective_scope`、`minimum_unit`、实际目标 ID 和影响数量由服务端规划器产生。段落属性不能声称只修改选中字符；段落提升须在界面显示，更大范围的变化必须明确确认。输入表达与控件不同须返回待澄清状态。

属性最小单位覆盖当前字符、段落、分节、表格、区域及字段／对象能力；这只是契约核对，实际编辑前仍须读取并核对引擎能力及目标可定位性。

## 4. HTTP 入口

沿用现有会话令牌、Origin 与回环 Host 校验。

| 方法及路径 | 行为 |
| --- | --- |
| `GET /api/tasks/{task_id}/versions/{version_id}/feedback-context` | 获取指定历史或当前版本的反馈上下文 |
| `POST /api/tasks/{task_id}/versions/{version_id}/feedback` | 校验并保存提交；202 表示已接收，尚待解析与编辑 |
| `GET /api/tasks/{task_id}/versions/{version_id}/feedback` | 列出此版本的接收凭据 |
| `GET /api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}` | 读取此版本的完整原始反馈 |

提交前先读取上下文，将其中的版本、预览和哈希填入请求。路径和正文的任务／版本必须一致。V0、过期工作起点、错误 PDF、修改过的文件与未知字段会被拒绝。本地错误响应不回显论文选区或反馈原话。

同一已接收请求可以在工作起点改变后重放取得原凭据；向旧版本提交新反馈，则必须先将它选作当前工作起点。当前没有新增“返回此版本继续修改”的 HTTP 入口，仍由第 7 步接入界面与 API。

无选区的咨询或全文需求可用 `requested_scope=document` 提交；其他范围需要选区提示，后续解析继续核对对象与实际作用范围。接收并不表示已经确认全文修改。

## 5. 版本和后续接入

原有 `version-node/1.0`、解析决定快照、编辑 manifest 与历史 Schema 不改写。反馈上下文只引用版本依据；用户回答产生的新解析决定仍单独保存，后续编译时作为明确的本轮输入结合父版本，不能原地改变历史版本引用。

`feedback-rule-snapshot/1.0` 定义父快照和局部例外产生版本，编译器实现、快照持久化、祖先关系验证、来源重放、冲突计算和例外重新定位留到第 5–7 步。第一步上下文的 `feedback_rules_snapshot_id` 为 `null`。已有 `AcademicEditor.execute()` 仍只接受来源重放通过的解析决定快照，不能直接传入新的反馈候选或反馈快照。

局部规则的 `anchor` 保留原始位置，`resolved_anchor` 可记录后续基础版本中的定位结果，`origin_version_id` 不改变。新快照中的局部规则只有重新定位到该快照绑定的版本和 DOCX 哈希后才能标为 `verified`；未定位的继承项保持 `pending_target`。实际重新定位与来源／祖先验证仍由后续编译器完成。

确认与冲突决定目前仅有契约和交叉校验函数，没有写接口；下一阶段接入时还须验证实际目标、最新工作指针并原子追加决定。这避免仅凭客户端指定的 ID 就声称用户已经确认。

## 6. 验证

新增测试在 `tests/feedback/`，覆盖 Schema 同步、原话保护、属性与单位、UTF-16、范围提升、解析分类、确认候选、冲突决定、锚点身份、文件与记录完整性、并发幂等、读取隔离、工作版本竞争、历史依据及重启恢复。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/export_feedback_schemas.py
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/feedback -q --basetemp runtime/pytest-feedback-step1
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -q --basetemp runtime/pytest-autoformat-feedback-step1
```

真实 PDF.js 操作、跨行定位、Word 排版比对与新 DOCX 编辑不属于本阶段验收。

验收结果：新增反馈测试 **52 项通过**；AutoFormat 全量 **113 passed / 5 skipped**；项目内解析副本 **391 passed / 2 skipped**。AutoFormat 的跳过项是未配置真实渲染器的既有测试；副本跳过项为 Windows 不适用的 Linux 隔离检查。按副本原有规则排除未复制部署文件对应的基础设施测试。`git diff --check` 通过。当前虚拟环境未安装 Ruff，未执行该工具；没有为此调整依赖。
