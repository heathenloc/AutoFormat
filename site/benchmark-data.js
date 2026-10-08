// Replace the values here when measured benchmarks are available. No UI changes needed.
// Numeric values remain illustrative until replaced. Source copy is supplied by the product owner.
window.autoformatBenchmarkData = {
  status: "mock",
  methodology: { "zh-CN": "数据来源于20份内部测试结果", en: "Data from 20 internal tests." },
  quality: [
    {
      key: "extractionF1", before: 0.78, after: 0.93, direction: "higher",
      format: "decimal", precision: 2, scaleMax: 1,
      improvement: { mode: "relative" },
      copy: {
        "zh-CN": { label: "格式要求提取 F1", description: "提取的准确性与覆盖率", method: "扩充领域词汇与中英文示例；优化提取／审计 Prompt；用漏提与误提取样本回归。" },
        en: { label: "Extraction F1", description: "Extraction precision and coverage", method: "Expand domain vocabulary and bilingual examples; tune extraction and audit prompts; regress missing and incorrect extractions." },
      },
    },
    {
      key: "scopeAccuracy", before: 81, after: 95, direction: "higher",
      format: "percent", precision: 0, scaleMax: 100,
      improvement: { mode: "points", multiplier: 1, unit: "percentagePoints", presentation: "arrowPercent" },
      copy: {
        "zh-CN": { label: "对象与作用范围准确率", description: "正确识别修改对象与适用范围", method: "优化条款切分与相邻上下文；补充章节、字符、条件与例外示例；核验完整作用范围。" },
        en: { label: "Scope Accuracy", description: "Correct targets and applicable scope", method: "Refine clause boundaries and adjacent context; add examples of sections, characters, conditions and exceptions; validate the complete scope." },
      },
    },
    {
      key: "unsupportedCandidates", before: 12, after: 3, direction: "lower",
      format: "percent", precision: 0, scaleMax: 15,
      improvement: { mode: "relative" },
      copy: {
        "zh-CN": { label: "无原文支持候选占比", description: "程序过滤前，缺少原文依据的候选比例", method: "引用真实证据 ID；加入示例与模板误判反例；Schema 校验后再核对原文证明。" },
        en: { label: "Unsupported Candidates", description: "Unsupported candidates before filtering", method: "Require real evidence IDs; add counterexamples for template and example confusion; verify source support after schema validation." },
      },
    },
  ],
  efficiency: [
    {
      key: "latency", before: 18.4, after: 7.2, direction: "lower",
      format: "seconds", precision: 1,
      improvement: { mode: "relative" },
      copy: {
        "zh-CN": { label: "Brief 解析 P95 耗时", description: "95% 的解析任务可在此时间内完成", method: "对照思考模式与输出长度；优化分块及争议分析触发条件；设置超时与有限重试。" },
        en: { label: "P95 Parsing Latency", description: "Time within which 95% of parses finish", method: "Compare thinking mode and output limits; optimize chunks and dispute-analysis triggers; bound timeouts and retries." },
      },
    },
    {
      key: "tokens", before: 8400, after: 4000, direction: "lower",
      format: "tokens", precision: 0,
      improvement: { mode: "relative" },
      copy: {
        "zh-CN": { label: "单任务 Token 用量", description: "一次任务的输入与输出 Token 总量，含失败与重试", method: "压缩无关上下文；按必要阶段调用；复用已验证结果与决定快照；统计失败与重试的 Token 用量。" },
        en: { label: "Tokens per Task", description: "Input and output tokens per task, including failures and retries", method: "Remove irrelevant context; call only necessary stages; reuse verified results and decisions; count tokens from failures and retries." },
      },
    },
  ],
};
