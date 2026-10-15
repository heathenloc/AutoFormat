"""Version 1.5 literal proofs with typed scope, conditions and expression aliases."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from brief_parser.academic_source_policy import classify_evidence, ordered_evidence, scope_match
from brief_parser.compilers.academic_common_v1_3 import AcademicCommonFormatExtractor as LiteralExtractor, _Item, _TARGET, _SIZES, _MODAL, _FONT
from brief_parser.compilers.academic_scope import analyze_rules, axis, base_scope, SemanticAnalysisLimit
from brief_parser.domain.academic_format import AcademicFormatIssue, AcademicFormatRule, AcademicFormatRuleSet, AcademicTarget, AcademicValue, finite_value
from brief_parser.domain.academic_semantics import AcademicCondition, AcademicConstraint, AcademicRuleSemantics
from brief_parser.domain.enums import EvidenceMatchStatus
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.compilers.academic_expressions import normalize_expression, canonical_font
from brief_parser.validators.academic_decisions import validate_format_value

VERSION = "academic-common-format/1.5"
LABELS = {"参考文献标题": "bibliography_heading", "所有标题": "heading", "各级标题": "heading", "全文": "document_text",
          "中文摘要": "abstract", "英文摘要": "abstract", "英数字": "latin_digits", "字母数字": "latin_digits",
          "全部文字": "document_text", "脚注": "footnote", "尾注": "endnote", "页眉": "header", "页脚": "footer",
          "表题": "table_caption", "表注": "table_caption", "文中引用": "citation", "引文": "citation",
          "中文": "document_text", "汉字": "document_text", "西文": "latin_text", "英文": "latin_text", "数字": "document_text"}
LABELS.update({"摘要标题": "abstract_heading", "目录标题": "toc_heading", "致谢": "acknowledgements", "附录": "appendix"})
LABELS.update({"一二三四五六七八九"[level - 1] + "级标题": f"heading_{level}" for level in range(5, 10)})
EXT_TARGET = re.compile("^(?:" + "|".join(sorted(map(re.escape, LABELS), key=len, reverse=True)) + ")")
SCRIPT = re.compile(r"^(?:的)?(英文字母和数字|英文及数字|字母与数字|英数字|中文|汉字|英文字母|英文字符|英文|西文|数字|所有字符)(?:文字|字符)?")
REGIONS = {"前置部分": "front_matter", "正文": "body", "摘要": "abstract", "目录": "toc", "参考文献": "bibliography", "附录": "appendix", "致谢": "acknowledgements"}
CONDITION = re.compile(r"纸质(?:合订)?版|打印版|电子版|系统上传(?:版)?|上传版")
UNKNOWN = re.compile(r"如果|若|仅在|视情况|必要时|按需要|某章|指定章节|本章|特殊情况下")
CHAPTER = re.compile(r"第([一二三四五六七八九十百\d]+)章")
ORDINAL = re.compile(r"第([一二三四五六七八九十\d]+)(?:个|张)?(?=表格|表头|表内文字)")
SIZE_RANGE = re.compile(r"(小[一二三四五六](?:号)?|[一二三四五六七八]号|小?[1-8]号|\d+(?:\.\d+)?\s*(?:pt|磅)?)\s*(?:至|到|[～~—–-])\s*(小[一二三四五六](?:号)?|[一二三四五六七八]号|小?[1-8]号|\d+(?:\.\d+)?\s*(?:pt|磅)?)", re.I)


def integer(text):
    if text.isdigit():
        return int(text)
    numbers = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if "十" in text:
        tens, ones = text.split("十", 1)
        return numbers.get(tens, 1) * 10 + numbers.get(ones, 0)
    return numbers.get(text)


def script_name(label):
    if label in {"中文", "汉字"}:
        return "chinese"
    if label == "数字":
        return "digits"
    if "数字" in label or label == "英数字":
        return "latin_digits"
    return "all" if label == "所有字符" else "latin"


def parse_condition(text):
    labels = list(dict.fromkeys(match.group() for match in CONDITION.finditer(text)))
    unknown = UNKNOWN.search(text)
    if not labels and not unknown:
        return None, {}, text
    media = {"print" if "纸质" in label or "打印" in label else "electronic" for label in labels}
    known = not unknown and len(media) == 1 and not re.search(r"或者|或|除.*外|不是|不属于|不适用|不采用|非(?:纸质|打印|电子|系统上传|上传)版", text)
    filters = {"medium": axis(media)} if known else {}
    if known and any("上传" in label for label in labels):
        filters["channel"] = axis(["system_upload"])
    condition = AcademicCondition(original_text="、".join(labels) if known else text.strip(), resolution="known" if known else "unknown",
                                  reason="提交场景可归一；当前任务场景仍需核对。" if known else "条件逻辑尚不能确定，保留原文和格式值。")
    stripped = CONDITION.sub("", text)
    stripped = re.sub(r"^(?:仅在|在|当|如果|若)\s*", "", stripped).lstrip("：: ，,")
    return condition, filters, stripped


@dataclass
class Context:
    role: str
    evidence: object
    filters: dict
    condition: AcademicCondition | None
    script: str


@dataclass
class Candidate:
    item: _Item
    filters: dict
    condition: AcademicCondition | None
    constraint: AcademicConstraint


class AcademicCommonFormatExtractor(LiteralExtractor):
    def extract(self, ir):
        if ir.domain_pack.id != "academic_paper":
            raise ValueError("Common academic extraction requires academic_paper IR.")
        sources = {source.source_id: source for source in ir.source_manifest}
        decisions = {item.evidence_id: item for item in classify_evidence(ir.evidence_index.values())}
        contexts, candidates = {}, []
        for ref in ordered_evidence(ir.evidence_index.values()):
            if (ref.match_status != EvidenceMatchStatus.EXACT or sources[ref.source_id].extraction_status != "complete"
                    or ref.locator.section_path[:1] in (["header"], ["footer"])):
                continue
            key = (ref.source_id, ref.block_id)
            decision = decisions[ref.evidence_id]
            if decision.source_class == "out_of_scope":
                match = _TARGET.match(ref.quote.strip())
                if match:
                    contexts[key] = Context(self._role(match.group(1)), ref, {}, None, "all")
                continue
            if decision.source_class != "explicit_requirement":
                contexts.pop(key, None)
                continue
            existing_context = contexts.get(key)
            found, context = self.parse_clause(ref, existing_context)
            if not found and existing_context is None:
                section_context = self.section_context(ref, ir.evidence_index)
                if section_context is not None:
                    found, context = self.parse_clause(ref, section_context)
            path_condition, path_filters, _ = parse_condition(" / ".join(ref.locator.section_path))
            if path_condition:
                for index, candidate in enumerate(found):
                    if candidate.condition is None:
                        found[index] = replace(candidate, filters={**path_filters, **candidate.filters}, condition=path_condition)
                    elif (path_condition.resolution == "unknown" or candidate.condition.resolution == "unknown"
                          or path_filters != {key: value for key, value in candidate.filters.items() if key in {"medium", "channel"}}):
                        found[index] = replace(candidate, filters={key: value for key, value in candidate.filters.items() if key not in {"medium", "channel"}},
                                               condition=AcademicCondition(original_text=path_condition.original_text + " / " + candidate.condition.original_text,
                                                                           resolution="unknown", reason="章节与条款条件组合需核对。"))
                if context and context.condition is None:
                    context = replace(context, filters={**path_filters, **context.filters}, condition=path_condition)
            candidates.extend(found)
            if context:
                contexts[key] = context
            else:
                contexts.pop(key, None)
        rules, issues = [], []
        for index, candidate in enumerate(candidates):
            item = candidate.item
            if item.property_id == "font.family" and isinstance(item.value, str):
                item = replace(item, value=canonical_font(item.value))
            if (not finite_value(item.value) or item.property_id == "font.size" and isinstance(item.value, (int, float)) and item.value <= 0):
                item = replace(item, value=None, problem="格式数值超出可验证范围，字号须为正数。")
            identifier = self._id("reqfmt", ir.artifact_id, item.evidence.evidence_id, item.role, item.property_id, str(index))
            refs = ([item.context_evidence] if item.context_evidence else []) + [item.evidence]
            refs = list({ref.evidence_id: ref for ref in refs}.values())
            if item.problem or item.value is None:
                issues.append(AcademicFormatIssue(source_requirement_id=identifier,
                    status=item.issue_status or ("ambiguous_target" if item.property_id == "target.classification" else "unsupported" if item.property_id == "unclassified.format_property" else "needs_value"),
                    reason=item.problem or "尚未给出明确格式值。", next_action="核对原文，补充具体值或适用范围。",
                    evidence_ids=[ref.evidence_id for ref in refs], target=AcademicTarget(object_kind=self._object_kind(item.role, item.property_id), semantic_role=item.role, selector="semantic_role_scope"),
                    property_id=item.property_id, original_text=item.original))
                continue
            try:
                scope = base_scope(item.role, item.property_id, item.character_scope, candidate.filters)
            except ValueError:
                issues.append(AcademicFormatIssue(source_requirement_id=identifier, status="ambiguous_target", reason="包含与排除范围相互抵消。",
                                                  next_action="核对对象范围。", evidence_ids=[ref.evidence_id for ref in refs], property_id=item.property_id, original_text=item.original))
                continue
            semantics = AcademicRuleSemantics(scope=scope, constraint=candidate.constraint, condition=candidate.condition)
            status = "pending_condition" if candidate.condition else "check_only" if candidate.constraint.operator != "eq" else "verified"
            filtered = bool(candidate.filters) or item.role in {"heading", "document_text"}
            requested = "document" if item.role in {"page", "document_text"} else "same_kind"
            rules.append(AcademicFormatRule(schema_version="academic-format-rule/1.1", rule_id=self._id("fmt", identifier), source_requirement_id=identifier,
                source_kind="brief_explicit", source_artifact_id=ir.artifact_id, source_version=f"{ir.artifact_id}:v{ir.artifact_version}", evidence_refs=refs,
                target=AcademicTarget(object_kind=self._object_kind(item.role, item.property_id), semantic_role=item.role,
                                      selector="semantic_role_scope" if filtered else "semantic_role"),
                property_id=item.property_id, value=AcademicValue(original_text=item.original, normalized=item.value, unit=item.unit, dictionary_version=VERSION),
                character_scope=item.character_scope, condition=candidate.condition.original_text if candidate.condition else None,
                requested_scope=requested, effective_scope=requested, status=status, semantics=semantics,
                reason="原文格式值和范围已验证；条件或区间不自动选定。" if status != "verified" else "原文格式值和适用范围已通过确定性校验。"))
        deduplicated = {}
        for rule in rules:
            key = json.dumps([rule.property_id, rule.value.normalized, rule.value.unit, rule.semantics.model_dump()], sort_keys=True, ensure_ascii=False)
            previous = deduplicated.get(key)
            if previous:
                refs = {ref.evidence_id: ref for ref in previous.evidence_refs}
                refs.update({ref.evidence_id: ref for ref in rule.evidence_refs})
                deduplicated[key] = previous.model_copy(update={"evidence_refs": list(refs.values())})
            else:
                deduplicated[key] = rule
        rules = list(deduplicated.values())
        try:
            relations, conflicts, fragments = analyze_rules(rules)
        except SemanticAnalysisLimit as exc:
            raise BriefParserError(ErrorCode.SOURCE_PARSER_RESOURCE_LIMIT, "Brief 的规则范围组合超出当前解析上限；本次未生成可执行结果。") from exc
        for index, rule in enumerate(rules):
            related = [item for item in conflicts if rule.rule_id in item.rule_ids]
            if related:
                rules[index] = rule.model_copy(update={"status": "pending_conflict" if any(item.certainty == "definite" for item in related) else "pending_condition",
                                                     "reason": "仅相交范围待定；无冲突分片单独保留，不设自动优先级。"})
        return AcademicFormatRuleSet(schema_version="academic-format-rule-set/1.5", compiler_version="1.5.0",
                                    source_artifact_id=ir.artifact_id, source_artifact_version=ir.artifact_version, domain_pack=ir.domain_pack,
                                    rules=rules, issues=issues, relations=relations, conflicts=conflicts, fragments=fragments)

    @staticmethod
    def section_context(ref, evidence_index):
        """Use an exact named source heading, never visual template appearance.

        Only the innermost heading is considered. A chapter-title convention
        without an explicit level must not silently become heading_1.
        """
        if not ref.locator.section_path or ref.locator.table is not None or ref.locator.paragraph is None:
            return None
        label = ref.locator.section_path[-1]
        text = normalize_expression(label).strip()
        match = _TARGET.fullmatch(text) or EXT_TARGET.fullmatch(text)
        if not match:
            return None
        role = LABELS[text] if text in LABELS else LiteralExtractor._role(match.group(1))
        headings = [entry for entry in evidence_index.values()
                    if entry.source_id == ref.source_id and entry.quote.strip() == label
                    and entry.locator.section_path == ref.locator.section_path
                    and entry.locator.paragraph is not None and entry.locator.paragraph < ref.locator.paragraph
                    and entry.match_status == EvidenceMatchStatus.EXACT]
        if not headings:
            return None
        heading = max(headings, key=lambda entry: (entry.locator.paragraph, entry.evidence_id))
        filters = {}
        if text in {"中文摘要", "英文摘要"}:
            filters["object_language"] = axis(["chinese" if text.startswith("中文") else "english"])
        script = "latin_digits" if role == "latin_digits" else "latin" if role == "latin_text" else "all"
        return Context(role, heading, filters, None, script)

    def parse_clause(self, ref, context):
        raw_text = normalize_expression(ref.quote.strip())
        if _TARGET.match(raw_text) or EXT_TARGET.match(raw_text):
            condition, filters, text = None, {}, raw_text
        else:
            condition, filters, text = parse_condition(raw_text)
        explicit_scope = False
        for pattern, name in ((CHAPTER, "chapter"), (ORDINAL, "object_ordinal")):
            match = pattern.match(text)
            if match and (number := integer(match.group(1))) is not None and number > 0:
                filters[name] = axis([str(number)])
                text = text[match.end():].lstrip("的 ：:,，")
                explicit_scope = True
        exception = re.search(r"除(.+?)外", text)
        if exception:
            excluded = exception.group(1)
            levels = re.findall(r"([一二三四1-4])级标题", excluded)
            regions = [REGIONS[label] for label in re.split(r"[、和与]", excluded) if label in REGIONS]
            if levels:
                filters["roles"] = axis(None, ["heading_" + str(integer(value)) for value in levels])
            elif regions:
                filters["regions"] = axis(None, regions)
            else:
                condition = AcademicCondition(original_text=exception.group(), resolution="unknown", reason="排除范围未识别。")
            text = (text[:exception.start()] + text[exception.end():]).lstrip("，, ：:")
            explicit_scope = True
        for label, region in REGIONS.items():
            if re.match(re.escape(label) + r"(?:部分|的)?(?:页码|页眉|页脚)", text):
                if region == "front_matter":
                    filters["region_zone"] = axis(["front_matter"])
                else:
                    filters["regions"] = axis([region])
                    if region == "body":
                        filters["region_zone"] = axis(["body"])
                text = re.sub("^" + re.escape(label) + r"(?:部分|的)?", "", text)
                explicit_scope = True
                break
        legacy, extended = _TARGET.match(text), EXT_TARGET.match(text)
        if not legacy and not extended and condition:
            # An unknown predicate can precede a clearly named formatting
            # object; retain its value without claiming predicate resolution.
            for offset in range(len(text)):
                suffix = text[offset:]
                if _TARGET.match(suffix) or EXT_TARGET.match(suffix):
                    text = suffix
                    legacy, extended = _TARGET.match(text), EXT_TARGET.match(text)
                    break
        chosen = extended if extended and (not legacy or extended.end() >= legacy.end()) else legacy
        direct, script = bool(chosen), "all"
        if chosen:
            label = chosen.group()
            role = LABELS[label] if chosen is extended else self._role(chosen.group(1))
            if label in {"中文摘要", "英文摘要"}:
                filters["object_language"] = axis(["chinese" if label.startswith("中文") else "english"])
            if role in {"latin_text", "latin_digits"}:
                script = "latin_digits" if role == "latin_digits" else "latin"
            elif label in {"中文", "汉字", "数字"}:
                script = script_name(label)
            rest = text[chosen.end():].lstrip("：: ，,的\t")
            directive = bool(re.search(r"[：:]", text) or _MODAL.search(text) or rest.startswith("用")
                             or re.search(r"[（(].*[）)]", rest))
            if role.startswith("heading_") and ((context and context.role == "toc") or ref.locator.section_path[-1:] == ["目录"]):
                role = "toc_" + role
                directive = True
        elif context:
            role, rest, directive, script = context.role, text, True, context.script
            filters = {**context.filters, **filters}
            condition = condition or context.condition
        else:
            return [Candidate(item, filters, condition, AcademicConstraint()) for item in super()._parse_evidence(ref)], None
        found, active_role = [], role
        continuation_filters, continuation_condition = filters, condition
        for token in re.split(r"[，,；;、]", rest):
            token = token.strip(" 。.\t（()）")
            if not token or scope_match(token):
                continue
            local_condition, local_filters, token = parse_condition(token)
            if local_condition:
                # A newly named branch replaces the previous submission branch;
                # object filters remain. Following properties inherit this branch.
                local_filters = {**{key: value for key, value in filters.items() if key not in {"medium", "channel"}}, **local_filters}
                continuation_filters, continuation_condition = local_filters, local_condition
            else:
                local_filters, local_condition = continuation_filters, continuation_condition
            token_role, token = self._token_role(active_role, token)
            if token_role is None:
                found.append(Candidate(_Item(ref, role, "target.classification", token, None, problem="标题级别或作用对象表述不明确。"), filters, condition, AcademicConstraint()))
                continue
            if role != "toc":
                active_role = token_role
            prefix, current_script = SCRIPT.match(token), script
            if prefix:
                current_script = script_name(prefix.group(1))
                remainder = token[prefix.end():]
                if not remainder.startswith("字体"):
                    script = current_script
                token = remainder.lstrip("：: ")
            for item, constraint in self.semantic_token(ref, token_role, token, directive):
                # Legacy Chinese-font modifiers are retained for that property.
                effective_script = current_script if current_script != "all" else item.character_scope
                item = replace(item, original=ref.quote.strip() if raw_text != ref.quote.strip() else item.original,
                               character_scope=effective_script if item.property_id.startswith("font.") else "all",
                               context_evidence=context.evidence if context and (not direct or role.startswith("toc_heading_")) else None)
                found.append(Candidate(item, local_filters, local_condition, constraint))
        if context and context.role == "toc" and role.startswith("toc_heading_"):
            return found, context
        return (found, Context(role, ref, continuation_filters, continuation_condition, script)) if found else ([], None)

    @staticmethod
    def _token_role(role, token):
        match = re.match(r"([一二三四五六七八九])级标题", token)
        if match and (role == "heading" or role.startswith("heading_") or role == "toc" or role.startswith("toc_heading_")):
            prefix = "toc_heading_" if role == "toc" or role.startswith("toc_heading_") else "heading_"
            return prefix + str(integer(match.group(1))), token[match.end():].lstrip("：: ")
        if role == "heading" or role.startswith("heading_"):
            match = _TARGET.match(token)
            if match and match.group(1) in {"一级标题", "二级标题", "三级标题", "四级标题"}:
                return LiteralExtractor._role(match.group(1)), token[match.end():].lstrip("：: ")
        return LiteralExtractor._token_role(role, token)

    def semantic_token(self, ref, role, token, directive):
        def item(prop, value, unit=None, constraint=None):
            return (_Item(ref, role, prop, token, value, unit), constraint or AcademicConstraint())
        def size_result(result, consumed):
            remainder = token.replace(consumed, "")
            companions = [(value, AcademicConstraint()) for value in super(AcademicCommonFormatExtractor, self)._parse_token(ref, role, remainder, directive)
                          if value.property_id != "font.size"]
            return companions + result
        # Only an explicit value becomes a rule. Soft language, alternatives,
        # negatives and unresolved comparisons must not fall through to an
        # affirmative value parser.
        if re.search(r"建议|推荐|宜采用|可以使用|可选|或者|\boptional\b", token, re.I):
            from brief_parser.academic_source_policy import format_properties
            return [(_Item(ref, role, prop, token, None, problem="建议、可选或多候选格式尚未确定。", issue_status="check_only"), AcademicConstraint())
                    for prop in format_properties(token)]
        if directive:
            extra = self._extended_values(ref, role, token)
            if extra is not None:
                return extra
        if re.search(r"不得|不要|不应|禁止|避免|不采用|不使用|不加粗", token) and not re.search(r"不小于|不得小于|不低于|不得低于|不大于|不得大于|不超过", token):
            if not (len(list(_FONT.finditer(token))) == 1 and re.search(r"不得使用|禁止使用|不使用", token)):
                from brief_parser.academic_source_policy import format_properties
                return [(_Item(ref, role, prop, token, None, problem="否定格式表达尚不能归一为确定的属性值。", issue_status="check_only"), AcademicConstraint())
                        for prop in format_properties(token)]
        specific = re.fullmatch(r"(段前|段后|首行缩进|悬挂缩进|左缩进|右缩进)(?:间距)?\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(pt|磅|cm|厘米|mm|毫米|字符|字)", token, re.I)
        if specific and directive:
            name, number, raw_unit = specific.groups()
            prop = {"段前": "spacing_before", "段后": "spacing_after", "首行缩进": "first_line_indent", "悬挂缩进": "hanging_indent", "左缩进": "left_indent", "右缩进": "right_indent"}[name]
            unit = "characters" if raw_unit in {"字符", "字"} else "cm" if raw_unit.lower() in {"cm", "厘米", "mm", "毫米"} else "pt"
            value = float(number) / (10 if raw_unit.lower() in {"mm", "毫米"} else 1)
            return [item("paragraph." + prop, value, unit)]
        spacing = re.search(r"(?:行距.*?(?:固定值|最小值)|(?:固定值|最小值).*?行距)\s*(\d+(?:\.\d+)?)\s*(pt|磅)", token, re.I)
        if spacing and directive:
            amount = float(spacing.group(1))
            if amount <= 0:
                return [(_Item(ref, role, "paragraph.line_spacing", token, None, problem="行距必须为正值。"), AcademicConstraint())]
            return [item("paragraph.line_spacing", {"mode": "atLeast" if "最小值" in token else "exact", "amount": amount}, "pt")]
        size_range = SIZE_RANGE.search(token)
        if size_range and re.search(r"段前|段后|行距|边距|缩进|线宽", token) and "字号" not in token:
            # Physical lengths must never fall through to the font-size parser.
            return [(_Item(ref, role, "unclassified.format_property", token, None, problem="该属性的区间格式尚未支持。"), AcademicConstraint())]
        stated_units = size_range and (all(re.search(r"号|小", value) for value in size_range.groups()) or re.search(r"pt|磅", size_range.group(), re.I))
        if size_range and stated_units and directive and not re.search(r"或者|或|不得|禁止", token):
            values = [self.point_value(value, allow_bare=True) for value in size_range.groups()]
            if all(value is not None for value in values):
                low, high = sorted(values)
                return size_result([item("font.size", {"min": low, "max": high}, "pt", AcademicConstraint(operator="between", lower=low, upper=high))], size_range.group())
        bound = re.search(r"字号\s*(?:为|是|在)?\s*(不小于|不得小于|至少|不低于|不得低于|不大于|不得大于|不超过|至多|最多)\s*(.+)", token)
        suffix = re.search(r"(?:字号\s*(?:为|是|在)?\s*)?([\d.]+\s*(?:pt|磅)|小[一二三四五六](?:号)?|[一二三四五六七八]号|小?[1-8]号)\s*(?:及)?(以上|以下)", token, re.I)
        if suffix and re.search(r"段前|段后|行距|边距|缩进|线宽", token) and "字号" not in token:
            suffix = None
        if (bound or suffix) and directive:
            value = self.point_value(bound.group(2) if bound else suffix.group(1))
            if value is None:
                return [(_Item(ref, role, "font.size", token, None, problem="字号约束缺少可确认的单位或字号名称。"), AcademicConstraint())]
            minimum = bound.group(1) in {"不小于", "不得小于", "至少", "不低于", "不得低于"} if bound else suffix.group(2) == "以上"
            return size_result([item("font.size", {"min" if minimum else "max": value}, "pt", AcademicConstraint(operator="gte" if minimum else "lte", lower=value if minimum else None, upper=None if minimum else value))], (bound or suffix).group())
        fonts = list(_FONT.finditer(token))
        if len(fonts) == 1 and directive and re.search(r"不得使用|禁止使用|不使用", token) and not re.search(r"或者|或", token):
            return [item("font.family", fonts[0].group(), constraint=AcademicConstraint(operator="ne"))]
        if re.search(r"不小于|不得小于|不低于|不得低于|不大于|不得大于|不少于|不超过|大于|小于|以上|以下|至少|至多|最多", token):
            return [(replace(value, value=None, problem="该比较约束尚未支持；不将边界当作固定格式值。"), AcademicConstraint())
                    for value in super()._parse_token(ref, role, token, directive)]
        return [(value, AcademicConstraint()) for value in super()._parse_token(ref, role, token, directive)]

    @staticmethod
    def _extended_values(ref, role, token):
        def result(prop, value, unit=None):
            try:
                validate_format_value(prop, value, unit)
            except ValueError:
                return [(_Item(ref, role, prop, token, None, problem="格式值或单位不符合已注册的类型。"), AcademicConstraint())]
            return [(_Item(ref, role, prop, token, value, unit), AcademicConstraint())]
        # Full-token matching prevents a numeric value for one attribute from
        # being reused for another, or an unknown font consuming nearby text.
        font = re.fullmatch(r'(?:使用\s*)?字体\s*(?:使用|为|是|采用|选用|:|：)?\s*["“\x27]([^"”\x27]+)["”\x27]', token)
        if font:
            return result("font.family", canonical_font(font.group(1)))
        simple_font = re.fullmatch(r"(?:使用\s*)?字体\s*(?:使用|为|是|采用|选用|:|：)?\s*([A-Za-z][A-Za-z0-9 -]{0,79})", token)
        if simple_font and not re.search(r"建议|或者|或|不得|禁止|不使用", token):
            return result("font.family", canonical_font(simple_font.group(1)))
        if re.fullmatch(r"(?:使用|采用)?(?:(?:不|不得|不应|禁止)(?:使用)?(?:加粗|粗体)|取消加粗|非粗体|加粗|粗体)", token):
            return result("font.bold", not bool(re.search(r"不|禁止|取消|非", token)))
        if re.fullmatch(r"(?:使用|采用)?(?:(?:不|不得|不应|禁止)(?:使用)?斜体|取消斜体|斜体|斜体字)", token):
            return result("font.italic", not bool(re.search(r"不|禁止|取消", token)))
        for label, prop in (("与下段同页", "paragraph.keep_with_next"), ("段中不分页", "paragraph.keep_together"),
                            ("段前分页", "paragraph.page_break_before"), ("对齐文档网格", "paragraph.snap_to_grid")):
            if re.fullmatch(r"(?:使用|开启|启用|关闭|取消|不)?" + label, token):
                return result(prop, not bool(re.match(r"关闭|取消|不", token)))
        if role == "page":
            paper = re.fullmatch(r"(?:纸张尺寸|纸张|使用|采用|为|尺寸|:|：|\s)*(A[345]|Letter)(?:纸)?", token, re.I)
            if paper:
                raw = paper.group(1)
                return result("page.paper_size", "Letter" if raw.casefold() == "letter" else raw.upper())
            if re.fullmatch(r"(?:页面方向|方向|采用|使用|为|:|：|\s)*(横向|纵向)", token):
                return result("page.orientation", "landscape" if "横向" in token else "portrait")
            margins = re.fullmatch(r"([上下左右]{1,4})(?:页)?边距\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米|pt|磅)", token, re.I)
            if margins:
                sides, amount, unit = margins.groups()
                value = float(amount) / (10 if unit.casefold() in {"mm", "毫米"} else 1)
                unit = "pt" if unit.casefold() in {"pt", "磅"} else "cm"
                return [entry for side in dict.fromkeys(sides) for entry in result("page.margin." + {"上": "top", "下": "bottom", "左": "left", "右": "right"}[side], value, unit)]
            distance = re.fullmatch(r"(页眉距(?:顶端|上边界)?|页脚距(?:底端|下边界)?|装订线)\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米|pt|磅)", token, re.I)
            if distance:
                label, amount, unit = distance.groups()
                prop = "header_distance" if label.startswith("页眉") else "footer_distance" if label.startswith("页脚") else "gutter"
                value = float(amount) / (10 if unit.casefold() in {"mm", "毫米"} else 1)
                return result("page.margin." + prop, value, "pt" if unit.casefold() in {"pt", "磅"} else "cm")
        if role == "page_number":
            if re.fullmatch(r"(?:采用|使用|为|格式|:|：|\s)*(大写罗马数字|小写罗马数字|阿拉伯数字)", token):
                value = "upper_roman" if "大写" in token else "lower_roman" if "小写" in token else "arabic"
                return result("page_number.number_format", value)
            start = re.fullmatch(r"(?:起始值|起始页码|起始|从)\s*(?:为|是|:|：)?\s*(\d+)(?:开始)?", token)
            if start:
                return result("page_number.start", int(start.group(1)))
        if role == "toc":
            depth = re.fullmatch(r"(?:标题|中的标题)?(?:不能超过|最多|不超过|只列|列至|显示至)\s*([一二三四五六七八九1-9])级(?:标题)?", token)
            if depth:
                return result("toc.max_depth", integer(depth.group(1)))
        if role in {"table_caption", "figure_caption"}:
            position = re.fullmatch(r"(?:位于|置于|在|位置为|使用)?\s*(?:图|表|图表|表格|图片)?(?:的)?(上方|下方|上面|下面|在上|在下)", token)
            if position:
                return result("caption.position", "above" if "上" in position.group(1) else "below")
        spacing = re.fullmatch(r"(段前|段后)(?:间距)?\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(行|lines?)", token, re.I)
        if spacing:
            return result("paragraph.spacing_before" if spacing.group(1) == "段前" else "paragraph.spacing_after", float(spacing.group(2)), "lines")
        if re.fullmatch(r"(?:使用|采用|行距为|行距)?\s*(单倍行距|双倍行距)", token):
            return result("paragraph.line_spacing", 1 if "单" in token else 2, "multiple")
        spacing = re.fullmatch(r"行距\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)", token)
        if spacing:
            # A bare number has no unit; never infer multiple vs points.
            return [(_Item(ref, role, "paragraph.line_spacing", token, None, problem="行距数值缺少倍数或磅值单位。"), AcademicConstraint())]
        return None

    @staticmethod
    def point_value(text, *, allow_bare=False):
        original = text.strip()
        if re.fullmatch(r"小?[1-8]号", text.strip()):
            text = re.sub(r"[1-8]", lambda match: "一二三四五六七八"[int(match.group()) - 1], text)
        text = text.strip().removesuffix("号")
        if re.fullmatch(r"小[1-6]", text):
            text = "小" + "一二三四五六"[int(text[1]) - 1]
        if text in _SIZES:
            return _SIZES[text]
        if text + "号" in _SIZES:
            return _SIZES[text + "号"]
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:pt|磅)" + ("?" if allow_bare else ""), original, re.I)
        value = float(match.group(1)) if match else None
        return value if value is not None and 0 < value <= 100 else None
