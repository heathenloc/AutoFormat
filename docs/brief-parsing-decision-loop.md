# 第五项：解析侧决策闭环

> 2026-10-07 流程修订：待确认项在解析完成后、首次格式编辑前处理。用户逐项选择候选答案或明确暂时忽略，之后才能生成 V1；没有待确认项时直接继续。下文带历史日期的增量保留当时状态，当前流程以本修订和 `docs/pre-edit-review.md` 为准。


日期：2026-10-03。

## 已完成的范围

闭环为：读取不可变解析结果 → 生成带出处的问题 → 接收类型化回答 → 重新分析适用条件与冲突 → 保存新规则快照 → 返回剩余问题。首次仍只上传 Brief 和论文；问题接口在 V0 解析完成后开放。

| 情形 | 可用操作 | 规则结果 |
| --- | --- | --- |
| 纸质／电子／上传条件 | 明确提交场景 | 保留适用分支，去掉已确定的场景条件；不适用分支记录为排除 |
| 未知条件 | 确认适用或不适用；未知对象范围还须明确范围 | 适用后重新分析冲突；不适用时排除该条；本章／某章不能默认扩大到全部章节 |
| 相交范围冲突 | 选择列出的规则 | 只替换冲突交集，保留被替代规则的其余范围 |
| 模板与明文不同 | 保留明文，或选择列出的模板观察 | 保留真实来源；模板选择明确替代相交范围 |
| 同类模板有多个值 | 选择展示的真实观察 | 不默认取第一个值 |
| 明文未规定的模板属性 | 按类别明确接受或拒绝 | 接受后编译新规则；拒绝不生成规则 |
| 缺值、字号区间或上下界 | 提交确定的属性、值和单位；对象不明时同时明确对象与范围 | 校验类型，保留对象／章节／语言／字符范围，拒绝违反原约束的值 |
| 来源审计问题 | 类型化补充、忽略、跳过或暂缓（依问题能力） | 不支持的属性不能补成可执行规则 |
| 跳过／暂缓 | 保存决定 | 不猜值，不解除原规则的未确定状态；暂缓仍阻止后续模板确认阶段 |

字数、词数、篇幅和具体内容要求不进入这个闭环。

先处理条件、冲突、来源差异和其他解析未确定项，再开放未提及模板属性的类别确认。未能读取或解析的模板观察不能通过“确认模板”变成规则。没有类型化处理能力的观察即使明确确认，也只成为 `report_only / check_only` 项。

## 独立、不可变的契约

原始 `AcademicParseBundle/1.5`、`AcademicFormatRuleSet/1.4`、来源审计和模板观察保持不变。决策结果使用独立契约：

| 契约 | 用途 |
| --- | --- |
| `AcademicQuestionQueue/1.0` | 当前问题、允许的动作、来源、候选、所需论文基础版本与期望规则快照 |
| `AcademicDecisionRequest/1.0` | 幂等请求 ID、问题 ID、类型化回答、期望快照与可选修订对象 |
| `AcademicDecisionEvent/1.0` | 任务、原始 Bundle 哈希、时间、问题类型和回答 |
| `AcademicEffectiveRule/1.0` | 新规则值、完整范围、来源规则／证据／模板观察与决定引用 |
| `AcademicDecisionSnapshot/1.0` | 所有决定及效果、新规则、冲突、分片、剩余问题、父快照和内容哈希 |

JSON Schema 位于项目 `contracts/`。纯编译器在 `modules/brief_parsing/src/brief_parser/application/academic_decisions.py`；持久化在 `apps/api/src/autoformat/academic_decisions.py`。

`raw_answer` 只留作审计，不解释为命令。自由文本反馈解析属于后续入口；它须先编译为经过验证的结构化回答，才能进入本闭环。模型或客户端不能指定规则状态、伪造证据或直接提供执行指令。

## API 用法

所有入口沿用本地 API 的会话令牌和 Origin 校验。

| 方法与路径 | 返回／用途 |
| --- | --- |
| `GET /api/tasks/{task_id}/questions` | 当前队列；V0 即可读取并回答 |
| `POST /api/tasks/{task_id}/decisions` | 提交回答并原子保存事件、新快照与当前快照指针 |
| `GET /api/tasks/{task_id}/resolved-rules` | 当前完整决策快照，供后续格式编辑器读取 |
| `GET /api/tasks/{task_id}/rule-decisions/snapshots` | 不可覆盖的快照历史 |
| `GET /api/tasks/{task_id}/rule-decisions/snapshots/{snapshot_id}` | 指定历史快照 |
| `GET /api/tasks/{task_id}/rule-decisions/report` | 当前 Markdown 决策报告；可用 `snapshot_id` 查询历史 |
| `GET /api/tasks/{task_id}/questions?reopen_decision_id=…` | 不改动当前状态，生成撤回该决定后重新回答所需的队列 |

例如，先读取队列，再提交列出的冲突规则 ID。下面的 ID 均为示意，实际值从 API 读取：

```json
{
  "schema_version": "academic-decision-request/1.0",
  "request_id": "11111111111111111111111111111111",
  "base_version_id": "22222222222222222222222222222222",
  "expected_snapshot_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "question_id": "fmtq_从当前队列读取",
  "answer": {
    "action": "select_rule",
    "selected_id": "fmt_从问题候选读取"
  }
}
```

补字号的回答为 `{"action":"clarify_format","format":{"property_id":"font.size","normalized":13,"unit":"pt"}}`；不能更换问题属性或扩大已有范围。

当原文没有定位对象时，`format` 还须带注册的 `semantic_role` 和明确的 `scope.axes`，范围须落在所选对象／字符类型内；未知范围轴拒绝。已有明确范围的补值不能更换该范围。原文条件继续保留，不能借补目标绕过条件。

条件问题若为 `requires_scope=true`，回答 `confirm_condition / applies=true` 还须在 `answer.scope` 指定范围。例如“本章／某章”要明确章号，未知排除范围不能确认成原对象的全部范围；范围不得超过原规则。

修订回答时，先带旧 `decision_id` 读取重新打开的队列，再在新请求中提供 `supersedes_decision_id`、当前快照和原问题 ID。新事件明确取代旧事件，历史快照保留旧结论。修订只能针对原决定对应的问题；其他问题须单独回答。场景改变后，范围或候选不再匹配的旧答案标记为 `invalidated`，重新询问，不能静默迁移。

选择论文历史版本本身不改变解析结论。新提交仍需绑定当前论文工作版本；真正编辑时由编辑器选择该版本作为父版本。

## 存储与验证

- SQLite 保存追加式决定和快照。并发写入同时核对论文工作版本、DOCX 哈希和规则快照指针；只允许一个提交成为当前结果。
- 同请求 ID、同完整回答可重复取得原结果；同 ID 不同回答拒绝。
- 加载时校验快照哈希、实际 Brief 的重新验证结果、纯编译器重放、决定日志哈希与父快照链。历史数据被改动时返回验证失败。
- 不确定范围、未知属性、错误单位、非有限值、越界字号、未列出的规则／模板候选和跨任务回答均不能发布新快照。
- 最多 256 个事件；沿用规则范围分析的 512 条规则与组合上限。超限时拒绝本次发布，不截断结果。

没有实际文档编辑时，只保存决定和规则快照，不生成冗余论文 DOCX 版本。

## 验收与限制

针对性测试涵盖条件分支、未知条件、局部冲突余集、范围保留、模板阶段顺序与确认、跳过／暂缓、区间取值、修订与失效、幂等、并发、历史校验及跨任务拒绝。完整回归命令：

```powershell
# 项目根目录
.venv\Scripts\python.exe -X utf8 -m pytest tests -q
# 在 modules/brief_parsing 中
..\..\.venv\Scripts\python.exe -X utf8 -m pytest tests --ignore=tests/contract/test_infrastructure_baseline.py -q
```

复制版没有来源项目的 Docker、Compose、独立部署和 CI 文件，因此四个部署基础设施测试不属于本项目回归范围。Windows 上两项 Linux 隔离测试及需要实际渲染器／构建产物的集成测试仍按环境条件跳过。

本次最终结果：解析回归 314 通过、2 跳过；AutoFormat 集成回归 55 通过、5 跳过。复制来源校验为 180 个文件、8 个已记录改动、0 个不一致；`git diff --check` 通过。

使用已有《材料学院毕业论文模板2026》、B04、B05 的保存解析结果验证了基线问题队列和快照生成。检查记录在忽略目录 `runtime/brief_decisions_20261003/baseline-checks.json`，没有替真实用户回答或改动原文件。这些样本原解析使用 fake provider，未确定项较多；该检查不衡量识别准确率。

本项完成解析编译器、版本契约、持久化和 API。产品问答界面、任意自由文本回答解析、Brief 更新后跨版本迁移答案和更多编辑能力仍待后续开发。历史 Bundle 1.0–1.4 继续按原语义读取，决策编译只接收 1.5，不重新解释旧数据。未来改变决策语义时须升级契约／编译器并保留旧版解释能力。

`verified` 只表示解析侧类型与冲突校验通过。编辑器还须校验完整范围、源证明、自身操作能力和论文目标定位；`check_only`、未解决条件或冲突不得直接执行。目前 V1 发布链路仍生成原稿基线副本，不能据此声称已自动修好大部分论文格式。
