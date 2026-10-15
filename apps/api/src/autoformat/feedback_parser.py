"""Small, fully consumed feedback grammar. No model or Brief pipeline calls.

Unconsumed words, conditions and alternatives block interpretation. The copied
parser supplies only its spelling aliases, frozen size dictionary and validators.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from brief_parser.compilers.academic_expressions import canonical_font, normalize_expression
from brief_parser.compilers.academic_common_v1_3 import _SIZES
from brief_parser.compilers.academic_scope import base_scope
from brief_parser.domain.academic_semantics import ScopeAxis

from .feedback_contracts import FeedbackPartialRule, FeedbackRuleCandidate, FormatValue, content_hash, property_minimum_unit

PARSER_ID, PARSER_VERSION = "controlled-feedback", "1.0"
NUMBER = r"(?:\d+(?:\.\d+)?)"
UNIT = r"(?:characters|字符|厘米|毫米|磅|pt|cm|mm|行)"
UNITS = {"字符": "characters", "characters": "characters", "厘米": "cm", "毫米": "mm", "磅": "pt", "行": "lines"}
ROLES = {"正文": "body", "摘要标题": "abstract_heading", "摘要": "abstract", "关键词": "keywords",
    "目录标题": "toc_heading", "目录": "toc", "参考文献标题": "bibliography_heading", "参考文献": "bibliography",
    "页眉": "header", "页脚": "footer", "脚注": "footnote", "尾注": "endnote", "表头文字": "table_header",
    "表内文字": "table_body", "表格": "table", "表题": "table_caption", "图题": "figure_caption", "所有标题": "heading"}
ROLES.update({f"{label}级标题": f"heading_{number}" for number, label in enumerate("一二三四五六七八九", 1)})
ROLE_RE = re.compile("|".join(re.escape(key) for key in sorted(ROLES, key=len, reverse=True)))
FONTS = r"Times\s+New\s+Roman|Microsoft\s+YaHei|Arial(?:\s+(?:Black|Narrow))?|Calibri|Cambria|微软雅黑|宋体|黑体|楷体|仿宋|隶书|华文中宋"
SET = r"(?:改为|改成|修改为|调整为|设为|设成|为|使用|:|：)?\s*"
NEG = r"(?:取消|去掉|去除|不使用|不要|不得|不|无)?"


@dataclass
class Interpretation:
    kind: str = "new_rule"
    candidates: list[FeedbackRuleCandidate] = field(default_factory=list)
    understood: list[FeedbackPartialRule] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    existing_rule_ids: list[str] = field(default_factory=list)
    reason: str = "已识别格式需求，仍需核对目标、实际范围及既有规则冲突；尚未执行修改。"
    defect_properties: set[str] = field(default_factory=set)


def interpret(raw: str, requested_scope: str, source_hash: str, *, selected_role: str | None = None) -> Interpretation:
    result = Interpretation()
    text = normalize_expression(raw).strip()
    # A consultation must not silently become an instruction merely because it
    # mentions an executable value. Neither are Word styles learned from prose.
    if re.search(r"[?？]|为什么|为何|怎么|如何|是否|可以吗|能否|是什么|多少(?:号|磅|pt)|\b(?:why|how|can|could|should)\b", raw, re.I):
        return Interpretation(kind="question", reason="这是咨询，尚未形成修改指令；当前可记录问题，不执行格式操作。")
    if re.search(r"改写|润色|重写|编写|生成正文|新增章节|删除章节|图表来源|编造|参考文献条目|摘要.*\d+字|字数|词数|篇幅|文献数量|关键词数量|图片(?:尺寸|大小|位置)|图像分辨率", text):
        return Interpretation(kind="out_of_scope", reason="涉及内容、数量、篇幅或图片处理，超出当前格式微调范围；未生成格式规则。")
    defect = bool(re.search(r"还是|仍然|仍是|仍为|没有(?:改|变)|未(?:按|修改)|没(?:有)?改|不符合|未生效|没有生效", text))
    # Alternative, exclusion, recommendation and conditional syntax is not a
    # license to choose one value or discard an applicability restriction.
    complicated = bool(re.search(r"如果|除非|否则|仅在|当.*时|除了|除.*外|只在|不小于|不超过|至少|最多|大于|小于|建议|或者|或|之间|不含|但不|不改|除了|第[一二三四五六七八九十\d]+章|[<>≤≥]|\d\s*[-~～—至]\s*\d", text))
    quoted = []
    def protect(match):
        quoted.append(match.group(1) or match.group(2))
        return f"\uE100{len(quoted) - 1}\uE101"
    text = re.sub(r'["“]([^"”\r\n]+)["”]|\x27([^\x27\r\n]+)\x27', protect, text)
    broad_role = bool(re.search(r"所有|全部", text))
    explicit_roles = list(dict.fromkeys(ROLES[m.group()] for m in ROLE_RE.finditer(text)))
    role = explicit_roles[0] if len(explicit_roles) == 1 else selected_role if not explicit_roles and requested_scope == "same_kind" else None
    text = ROLE_RE.sub("", text)
    if len(explicit_roles) > 1:
        result.missing_fields.append("semantic_role")
    scripts = set()
    def script(match):
        value = match.group()
        scripts.update({"latin", "digits"} if value in {"英数字", "英文和数字", "字母和数字"} else
                       {"chinese"} if value in {"中文", "汉字", "中文字符"} else
                       {"digits"} if value in {"数字", "数字字符"} else {"latin"})
        return ""
    text = re.sub(r"英数字|英文和数字|字母和数字|中文字符|数字字符|英文字母|拉丁字母|中文|汉字|英文|西文|字母|数字", script, text)
    text_scope = "document" if "全文" in text else "same_kind" if broad_role or re.search(r"所有|全部|同类", text) else "paragraph" if re.search(r"整(?:个)?段落|这[一]?段|本段|所在段落|当前段落", text) else "selection" if re.search(r"选中文字|选中处|选区", text) else None
    text = re.sub(r"全文|所有|全部|同类(?:内容)?|整(?:个)?段落|这[一]?段|本段|所在段落|当前段落|选中文字|选中处|选区", "", text)
    atoms = []
    def consume(pattern, build):
        nonlocal text
        def replace(match):
            prop, value, unit = build(match)
            atoms.append((prop, value, unit))
            return " "
        text = re.sub(pattern, replace, text, flags=re.I)
    unit = lambda value: UNITS.get(value.casefold(), value.casefold())
    numeric = lambda value: float(value)
    # Specific dimensions are consumed before bare pt / Chinese size values.
    lengths = {"段前(?:间距|距离)?": "paragraph.spacing_before", "段后(?:间距|距离)?": "paragraph.spacing_after",
        "首行缩进": "paragraph.first_line_indent", "悬挂缩进": "paragraph.hanging_indent", "左缩进": "paragraph.left_indent", "右缩进": "paragraph.right_indent",
        "上页边距|上边距": "page.margin.top", "下页边距|下边距": "page.margin.bottom", "左页边距|左边距": "page.margin.left", "右页边距|右边距": "page.margin.right", "页边距": "page.margin.all"}
    for label, prop in lengths.items():
        consume(rf"(?:{label})\s*{SET}({NUMBER})\s*({UNIT})", lambda m, prop=prop: (prop, numeric(m[1]), unit(m[2])))
    consume(rf"行距\s*{SET}(?:固定值|固定|精确)\s*({NUMBER})\s*(pt|磅)", lambda m: ("paragraph.line_spacing", {"mode": "exact", "amount": numeric(m[1])}, "pt"))
    consume(rf"行距\s*{SET}(?:最小值|最小)\s*({NUMBER})\s*(pt|磅)", lambda m: ("paragraph.line_spacing", {"mode": "atLeast", "amount": numeric(m[1])}, "pt"))
    consume(rf"(?:行距\s*{SET}({NUMBER})\s*倍|({NUMBER})\s*倍行距)", lambda m: ("paragraph.line_spacing", numeric(m[1] or m[2]), "multiple"))
    consume(r"单倍行距|双倍行距", lambda m: ("paragraph.line_spacing", 1.0 if m[0] == "单倍行距" else 2.0, "multiple"))
    for label, prop in {"加粗|粗体": "font.bold", "斜体": "font.italic", "与下段同页": "paragraph.keep_with_next", "段中不分页": "paragraph.keep_together", "段前分页": "paragraph.page_break_before", "对齐网格": "paragraph.snap_to_grid"}.items():
        consume(rf"({NEG})(?:{label})", lambda m, prop=prop: (prop, not bool(m[1]), None))
    alignments = {"两端对齐": "both", "居中": "center", "居左": "left", "左对齐": "left", "居右": "right", "右对齐": "right"}
    consume("|".join(alignments), lambda m: ("paragraph.alignment", alignments[m[0]], None))
    consume(r"字体\s*" + SET + r"\uE100(\d+)\uE101", lambda m: ("font.family", canonical_font(quoted[int(m[1])]), None))
    consume(FONTS, lambda m: ("font.family", canonical_font(m[0]), None))
    def size(match):
        key = match[0].removesuffix("号") if match[0].startswith("小") else match[0]
        return "font.size", float(_SIZES[key]), "pt"
    consume(r"小[初一二三四五六](?:号)?|初号|[一二三四五六七八]号", size)
    consume(rf"(?<![\d.])({NUMBER})\s*(pt|磅)(?![A-Za-z0-9_.])", lambda m: ("font.size", numeric(m[1]), "pt"))
    consume(r"(?<![A-Za-z0-9])(?:A4|A3|A5|Letter)(?![A-Za-z0-9])", lambda m: ("page.paper_size", "Letter" if m[0].casefold() == "letter" else m[0].upper(), None))
    consume(r"横向|纵向", lambda m: ("page.orientation", "landscape" if m[0] == "横向" else "portrait", None))
    consume(r"三线表|全框线|无边框", lambda m: ("table.border_style", {"三线表": "three_line", "全框线": "all_borders", "无边框": "none"}[m[0]], None))
    mentioned = {"字体": "font.family", "字号|字体大小|字大小": "font.size", "对齐(?:方式)?": "paragraph.alignment", "行距": "paragraph.line_spacing", **lengths}
    for label, prop in mentioned.items():
        if re.search(label, text) and not any(p == prop for p, _, _ in atoms):
            atoms.append((prop, None, None))
        text = re.sub(label, "", text)
    # These words are syntax only. Arbitrary remaining words are never ignored.
    residue = re.sub(r"这里|此处|这些|这个|文字|段落|格式|纸张尺寸|纸张大小|纸张|页面|统一|改为|改成|修改为|调整为|设为|设成|使用|请|麻烦|帮我|需要|要求|必须|应当|一下|大一点|小一点|一点|调大|调小|增大|减小|修改|调整|设置|更改|换个|改|将|把|的|为|是|用|都|均|并且|并|以及|及|和|[\s,，、;；。.!！:：（）()]+", "", text)
    if defect:
        result.defect_properties = {p for p, _, _ in atoms}
        result.kind = "clarification_needed"; result.missing_fields = ["existing_rule_id"]
        result.reason = "这是已有规则的执行反馈，需先核对该处原本遵守的规则；不会把描述的现状当作新要求。"
        return result
    if complicated:
        result.missing_fields.append("applicability_scope")
    if residue:
        result.missing_fields.append("unrecognized_text")
    if not atoms:
        atoms.append((None, None, None)); result.missing_fields.append("property_id")
    if len(atoms) > 64:
        return Interpretation(kind="clarification_needed", missing_fields=["too_many_rules"], reason="一次反馈的格式条目过多，请拆开提交。")
    for number, (prop, value, value_unit) in enumerate(dict.fromkeys((p, str(v), u) for p, v, u in atoms)):
        # Retain original JSON value types, including booleans and spacing modes.
        actual = next(v for p, v, u in atoms if (p, str(v), u) == (prop, value, value_unit))
        cid = "fc:" + content_hash({"source": source_hash, "property": prop, "ordinal": number})[:24]
        try:
            typed_value = FormatValue(normalized=actual, unit=value_unit) if actual is not None else None
            script_name = next(iter(scripts)) if len(scripts) == 1 else "all"
            applicability = base_scope(role or "document_text", prop, script_name,
                {"characters": ScopeAxis(include=sorted(scripts))}) if prop and scripts else None
            if prop and scripts and not prop.startswith("font."):
                # base_scope deliberately removes script filters from paragraph
                # geometry. Preserve the requested restriction as clarification,
                # including combinations whose character_scope is otherwise all.
                applicability.axes["characters"] = ScopeAxis(include=sorted(scripts))
                result.missing_fields.append("character_scope")
            if prop and actual is not None and requested_scope == "same_kind" and role is None:
                result.understood.append(FeedbackPartialRule(candidate_id=cid, property_id=prop, value=typed_value, requested_scope=requested_scope))
                result.missing_fields.append("semantic_role")
            elif prop and actual is not None:
                result.candidates.append(FeedbackRuleCandidate(candidate_id=cid, property_id=prop, value=typed_value,
                    requested_scope=requested_scope, semantic_role=role, character_scope=script_name, applicability_scope=applicability))
            else:
                result.understood.append(FeedbackPartialRule(candidate_id=cid, property_id=prop, value=typed_value,
                    requested_scope=requested_scope, semantic_role=role))
                result.missing_fields.append("value" if prop else "property_id")
                if scripts: result.missing_fields.append("character_scope")
        except ValueError:
            result.understood.append(FeedbackPartialRule(candidate_id=cid, property_id=prop, semantic_role=role, requested_scope=requested_scope))
            result.missing_fields.append("value")
    for prop in {c.property_id for c in result.candidates}:
        values = {(str(c.value.normalized), c.value.unit) for c in result.candidates if c.property_id == prop}
        if len(values) > 1: result.missing_fields.append("conflicting_values")
    if text_scope and text_scope != requested_scope:
        promotion = text_scope == "paragraph" and requested_scope == "selection" and all(property_minimum_unit(c.property_id) == "paragraph" for c in result.candidates) and bool(result.candidates)
        if not promotion: result.missing_fields.append("requested_scope")
    if requested_scope == "document" and role not in {None, "document_text"}:
        result.missing_fields.append("requested_scope")
    if result.missing_fields:
        result.kind = "clarification_needed"
        result.reason = "已保留可识别部分；请补充缺值、统一作用范围或将复杂表达拆成明确需求。尚未执行修改。"
    result.missing_fields = list(dict.fromkeys(result.missing_fields))
    return result
