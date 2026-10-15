"""Read secured DOCX OOXML without opening Word, writing files or rendering.

Only declared logical properties are observed. Missing host defaults, ambiguous
style/table contexts and unresolved theme fonts remain unknown. Part paths are
resolved inside the ZIP; external relationships are never followed.
"""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from zipfile import ZipFile

from lxml import etree

from brief_parser.academic_source_policy_v1_0 import TARGET_LABEL, scope_match
from brief_parser.domain.template_layout import (
    TemplateDiagnostic, TemplateLocation, TemplateObservation,
    TemplatePropertyOrigin, TemplateSourceProfile,
)
from brief_parser.ports.document_ingestion import SecuredSource


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"w": W, "a": A}


def tag(name: str) -> str:
    return f"{{{W}}}{name}"


def attr(node, name: str, default=None):
    return node.get(tag(name), default) if node is not None else default


def text_of(node) -> str:
    return "".join(node.itertext()) if etree.QName(node).localname == "t" else "".join(node.xpath(".//w:t/text()", namespaces=NS))


def on_off(value: str | None) -> bool:
    if value in {None, "1", "true", "on"}:
        return True
    if value in {"0", "false", "off"}:
        return False
    raise ValueError("invalid on/off property")


@dataclass(frozen=True)
class _Layer:
    node: object
    part: str
    kind: str
    style_id: str | None = None


@dataclass
class TemplateReadResult:
    profiles: list[TemplateSourceProfile]
    observations: list[TemplateObservation]
    diagnostics: list[TemplateDiagnostic]


class DocxTemplateLayoutReader:
    def __init__(self, *, max_observations: int = 6000) -> None:
        if max_observations <= 0:
            raise ValueError("observation limit must be positive")
        self.max_observations = max_observations

    def read(self, sources: Iterable[SecuredSource]) -> TemplateReadResult:
        result = TemplateReadResult([], [], [])
        for source in sources:
            if source.kind != "docx":
                result.profiles.append(TemplateSourceProfile(
                    source_id=source.source_id, sha256=source.sha256, kind=source.kind,
                    classification="not_available", signal_codes=["docx_required_for_layout"],
                ))
                result.diagnostics.append(TemplateDiagnostic(
                    source_id=source.source_id, code="layout_not_available",
                    message="此来源只提取明文要求；模板逻辑版式读取目前支持 DOCX。",
                ))
                continue
            session = _DocxReadSession(source, self.max_observations)
            local = session.read()
            result.profiles.extend(local.profiles)
            result.observations.extend(local.observations)
            result.diagnostics.extend(local.diagnostics)
        return result


class _DocxReadSession:
    def __init__(self, source: SecuredSource, limit: int) -> None:
        self.source = source
        self.limit = limit
        self.observations = []
        self.diagnostics = []
        self._diagnostic_keys = set()
        self.parts = {}
        self.relationships = {}
        self.styles = {}
        self.defaults = {}
        self.default_conflicts = set()
        self.theme = None
        self.theme_part = None

    def diagnostic(self, code: str, message: str, location=None) -> None:
        key = (code, location.part if location else "", location.xpath if location else "")
        if key not in self._diagnostic_keys:
            self._diagnostic_keys.add(key)
            self.diagnostics.append(TemplateDiagnostic(
                source_id=self.source.source_id, code=code, message=message, location=location,
            ))

    def location(self, node, part: str, **indices) -> TemplateLocation:
        return TemplateLocation(part=part, xpath=node.getroottree().getpath(node), **indices)

    def origin(self, node, layer: _Layer, raw: str, attribute: str | None = None) -> TemplatePropertyOrigin:
        path = node.getroottree().getpath(node)
        if attribute:
            path += "/@w:" + attribute
        return TemplatePropertyOrigin(
            part=layer.part, xpath=path, layer=layer.kind, style_id=layer.style_id,
            raw_value=raw, node_sha256=hashlib.sha256(etree.tostring(node, method="c14n")).hexdigest(),
        )

    def emit(self, location: TemplateLocation, role: str, basis: str, region: str,
             prop: str, value, unit: str | None, origins: list, *, excerpt="", scope="all", reasons=()) -> None:
        if value is None and not reasons:
            reasons = ("property_value_unrecognized",)
        if len(self.observations) >= self.limit:
            self.diagnostic("observation_limit_reached", "版式观察达到数量上限；后续对象未读取。")
            return
        identity = json.dumps([self.source.source_id, self.source.sha256, location.model_dump(), prop, scope], sort_keys=True)
        self.observations.append(TemplateObservation(
            observation_id="obs_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
            source_id=self.source.source_id, source_sha256=self.source.sha256,
            semantic_role=role, role_basis=basis, region=region, property_id=prop,
            character_scope=scope, value=None if reasons else value, unit=unit,
            resolution="unresolved" if reasons else "resolved", reason_codes=list(reasons),
            location=location, origins=origins, text_excerpt=excerpt[:120],
        ))

    def read(self) -> TemplateReadResult:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        with ZipFile(BytesIO(self.source.content)) as archive:
            # The caller supplies the same security-checked immutable bytes used
            # for text ingestion. No external part target is fetched.
            for name in archive.namelist():
                if name.startswith("word/") and name.endswith(".xml") or name == "word/_rels/document.xml.rels":
                    try:
                        self.parts[name] = etree.fromstring(archive.read(name), parser)
                    except etree.XMLSyntaxError:
                        if name == "word/document.xml":
                            raise ValueError("DOCX main document XML is invalid") from None
                        self.diagnostic("part_xml_unreadable", f"无法读取版式部件 {name}；相关属性保持未确定。")
        document = self.parts.get("word/document.xml")
        if document is None:
            raise ValueError("DOCX has no main document")
        rels = self.parts.get("word/_rels/document.xml.rels")
        if rels is not None:
            for rel in rels:
                if rel.get("TargetMode") == "External":
                    continue
                target = rel.get("Target", "")
                name = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("word", target))
                if name.startswith("word/") and name in self.parts:
                    self.relationships[rel.get("Id")] = name
                    if rel.get("Type", "").endswith("/theme"):
                        self.theme_part, self.theme = name, self.parts[name]
        styles = self.parts.get("word/styles.xml")
        if styles is not None:
            duplicates = set()
            for node in styles.findall(tag("style")):
                sid = attr(node, "styleId")
                if sid in self.styles:
                    duplicates.add(sid)
                self.styles[sid] = node
            for sid in duplicates:
                del self.styles[sid]
            if duplicates:
                self.diagnostic("duplicate_style_id", "样式 ID 重复，相关继承值不能确定。")
            self.defaults = {attr(node, "type"): attr(node, "styleId") for node in self.styles.values()
                             if attr(node, "default") in {"1", "true", "on"}}
            for kind in self.defaults.copy():
                candidates = [node for node in self.styles.values() if attr(node, "type") == kind
                              and attr(node, "default") in {"1", "true", "on"}]
                if len(candidates) > 1:
                    self.default_conflicts.add(kind)
                    del self.defaults[kind]
                    self.diagnostic("default_style_ambiguous", "存在多个默认样式，相关继承值不能确定。")
        self.doc_defaults = styles.find(tag("docDefaults")) if styles is not None else None
        body = document.find(tag("body"))
        if body is None:
            raise ValueError("DOCX has no body")
        plain = text_of(body)
        labels = {re.sub(r"\s+", "", text_of(p)) for p in body.iter(tag("p"))}
        has_label = bool(re.search(r"模板|模版|样张", (self.source.filename or "") + plain[:6000]))
        anchors = sum(any(label.startswith(name) for label in labels) for name in ("摘要", "目录", "参考文献", "致谢"))
        instruction = bool(re.search(r"撰写规范|编写规定|撰写要求|写作规范|写作要求", plain[:250]))
        classification = ("template_candidate" if anchors >= 2 or has_label
                          else "instruction_document" if instruction else "uncertain")
        signals = (["template_label"] if has_label else []) + (["template_structure"] if anchors >= 2 else []) + (["instruction_title"] if instruction else [])
        profile = TemplateSourceProfile(source_id=self.source.source_id, sha256=self.source.sha256,
                                        kind="docx", classification=classification, signal_codes=signals)
        if classification != "template_candidate":
            self.diagnostic("template_source_unconfirmed", "尚不能确定该来源包含论文模板；版式只记录为参考观察。")
        region = "context_only" if instruction else "template_candidate" if classification == "template_candidate" else "uncertain"
        section = paragraph = table = 0
        section = 1
        active_role = "unclassified"
        section_roles = {}
        for node in body:
            if len(self.observations) >= self.limit:
                self.diagnostic("observation_limit_reached", "版式观察达到数量上限；后续对象未读取。")
                break
            if node.tag == tag("p"):
                paragraph += 1
                text = text_of(node)
                compact = re.sub(r"\s+", "", text)
                if classification == "template_candidate" and any(compact.startswith(name) for name in ("摘要", "目录", "参考文献", "致谢")):
                    region = "template_candidate"
                role, basis, active_role = self.paragraph_role(node, active_role)
                local_region = region
                if scope_match(text) or (TARGET_LABEL.match(text.strip()) and "：" in text and "（" not in text):
                    local_region = "context_only"
                self.paragraph(node, "word/document.xml", role, basis, local_region,
                               section=section, paragraph=paragraph)
                section_roles[section] = region
                sect = node.find("w:pPr/w:sectPr", NS)
                if sect is not None:
                    self.section(sect, section, section_roles.get(section, region))
                    section += 1
            elif node.tag == tag("tbl"):
                table += 1
                self.table(node, table, section, region)
            elif node.tag == tag("sectPr"):
                self.section(node, section, section_roles.get(section, region))
            elif node.tag == tag("sdt"):
                self.diagnostic("content_control_not_resolved", "内容控件中的版式尚未完整读取。", self.location(node, "word/document.xml"))
        for note_kind in ("footnote", "endnote"):
            part = f"word/{note_kind}s.xml"
            root = self.parts.get(part)
            if root is not None:
                for note in root.findall(tag(note_kind)):
                    if attr(note, "type") in {"separator", "continuationSeparator", "continuationNotice"}:
                        continue
                    for pindex, p in enumerate(note.findall(tag("p")), start=1):
                        self.paragraph(p, part, note_kind, "note_element", region, paragraph=pindex)
        for code, path, message in (
            ("textbox_layout_not_resolved", ".//w:txbxContent", "文本框版式暂未解析。"),
            ("revision_layout_not_resolved", ".//w:ins|.//w:del|.//w:pPrChange|.//w:rPrChange", "修订或历史属性需人工核对；修订对象的观察值不参与模板沿用分组。"),
            ("media_layout_not_resolved", ".//w:drawing|.//w:pict|.//w:object", "图片、绘图和嵌入对象的内部版式暂未解析。"),
        ):
            if any(root.xpath(path, namespaces=NS) for root in self.parts.values()):
                self.diagnostic(code, message)
        return TemplateReadResult([profile], self.observations, self.diagnostics)

    def style_chain(self, style_id, kind: str) -> tuple[list, bool]:
        chain, seen = [], set()
        while style_id:
            if style_id in seen or len(seen) >= 64:
                self.diagnostic("style_cycle", "样式继承有循环或链过长，继承值不能确定。")
                return [], True
            seen.add(style_id)
            style = self.styles.get(style_id)
            if style is None or attr(style, "type") != kind:
                self.diagnostic("style_reference_missing", "样式引用缺失或类型不符，继承值不能确定。")
                return [], True
            chain.append(style)
            style_id = attr(style.find(tag("basedOn")), "val")
        return list(reversed(chain)), False

    def layers(self, p, r=None, table_style=None):
        pstyle = attr(p.find("w:pPr/w:pStyle", NS), "val", self.defaults.get("paragraph"))
        pchain, uncertain = self.style_chain(pstyle, "paragraph")
        uncertain |= pstyle is None and "paragraph" in self.default_conflicts
        layers = []
        if self.doc_defaults is not None:
            layers.append(_Layer(self.doc_defaults, "word/styles.xml", "document_default"))
        if table_style:
            tchain, bad = self.style_chain(table_style, "table")
            uncertain |= bad or any(style.findall(tag("tblStylePr")) for style in tchain)
            layers += [_Layer(style, "word/styles.xml", "table_style", attr(style, "styleId")) for style in tchain]
        layers += [_Layer(style, "word/styles.xml", "paragraph_style", attr(style, "styleId")) for style in pchain]
        if r is not None:
            rstyle = attr(r.find("w:rPr/w:rStyle", NS), "val")
            if rstyle:
                chain, bad = self.style_chain(rstyle, "character")
                uncertain |= bad
                layers += [_Layer(style, "word/styles.xml", "character_style", attr(style, "styleId")) for style in chain]
            layers.append(_Layer(r, r.getroottree().docinfo.URL or "word/document.xml", "direct"))
        else:
            layers.append(_Layer(p, "word/document.xml", "direct"))
        return layers, uncertain

    def property_node(self, layer: _Layer, kind: str, name: str):
        if layer.kind == "document_default":
            return layer.node.find(f"w:{kind}Default/w:{kind}/w:{name}", NS)
        return layer.node.find(f"w:{kind}/w:{name}", NS)

    def effective(self, layers: list, kind: str, name: str, attribute="val"):
        found = []
        for layer in layers:
            node = self.property_node(layer, kind, name)
            if node is not None and (attribute is None or attr(node, attribute) is not None):
                raw = attr(node, attribute, "true") if attribute else etree.tostring(node).decode()
                found.append((raw, self.origin(node, layer, raw, attribute)))
        return (found[-1][0], [item[1] for item in found]) if found else (None, [])

    def paragraph_role(self, p, active):
        compact = re.sub(r"\s+", "", text_of(p))
        special = {"摘要": "abstract", "Abstract": "abstract", "目录": "toc", "参考文献": "bibliography", "致谢": "acknowledgements", "附录": "appendix"}
        for label, role in special.items():
            if compact == label or compact.startswith(label + "（"):
                return role + "_heading", "section_label", role
        sid = attr(p.find("w:pPr/w:pStyle", NS), "val", self.defaults.get("paragraph"))
        chain, bad = self.style_chain(sid, "paragraph")
        for style in chain:
            name = attr(style.find(tag("name")), "val", "")
            match = re.fullmatch(r"(?:TOC|目录)\s*([1-9])", name, re.I)
            if match:
                return f"toc_heading_{match[1]}", "toc_style", "toc"
        level = None
        for style in chain + [p]:
            raw = attr(style.find("w:pPr/w:outlineLvl", NS), "val")
            if raw is not None:
                level = int(raw) + 1 if raw.isdigit() and int(raw) < 9 else None
            name = attr(style.find(tag("name")), "val", "")
            match = re.fullmatch(r"(?:Heading|标题)\s*([1-9])", name, re.I)
            if match and level is None:
                level = int(match[1])
        if level and not bad:
            return f"heading_{level}", "outline_or_heading_style", "body"
        if active == "toc":
            match = re.match(r"TOC\s*([1-9])", sid or "", re.I)
            return f"toc_heading_{match[1]}" if match else "toc", "toc_region", active
        if compact.startswith("关键词") or compact.startswith("Keywords"):
            return "keywords", "section_label", active
        return (active if active in {"abstract", "bibliography", "acknowledgements", "appendix"} else "body"), "section_context_or_body_candidate", active

    def paragraph(self, p, part, role, basis, region, *, table_style=None, **indices):
        if p.xpath("ancestor::w:ins|ancestor::w:del|w:pPr/w:pPrChange", namespaces=NS):
            region = "context_only"
        layers, bad = self.layers(p, table_style=table_style)
        layers[-1] = _Layer(p, part, "direct")
        location = self.location(p, part, **indices)
        excerpt = text_of(p)

        def observe(prop, raw, origins, value, unit=None, reasons=()):
            if origins:
                inherited_bad = bad and origins[-1].layer != "direct"
                if value is None or isinstance(value, dict) and any(item is None for item in value.values()):
                    reasons = list(reasons) + ["property_value_unrecognized"]
                self.emit(location, role, basis, region, prop, value, unit, origins,
                          excerpt=excerpt, reasons=list(reasons) + (["style_context_unresolved"] if inherited_bad else []))

        for name, prop, normalize in (
            ("jc", "paragraph.alignment", lambda value: {"center": "center", "left": "left", "right": "right", "both": "both"}.get(value)),
            ("keepNext", "paragraph.keep_with_next", on_off),
            ("keepLines", "paragraph.keep_together", on_off),
            ("pageBreakBefore", "paragraph.page_break_before", on_off),
            ("snapToGrid", "paragraph.snap_to_grid", on_off),
        ):
            raw, origins = self.effective(layers, "pPr", name, None if name != "jc" else "val")
            if origins:
                raw = attr(self.property_node(layers[-1], "pPr", name), "val") if origins[-1].layer == "direct" and name != "jc" else raw
                if name != "jc":
                    raw, origins = self.effective_on_off(layers, "pPr", name)
                try:
                    value = normalize(raw)
                except ValueError:
                    value = None
                observe(prop, raw, origins, value, reasons=["property_value_unrecognized"] if value is None else [])
        for attr_name, prop in (("before", "paragraph.spacing_before"), ("after", "paragraph.spacing_after")):
            raw, origins = self.effective(layers, "pPr", "spacing", attr_name)
            if origins:
                automatic, auto_origins = self.effective(layers, "pPr", "spacing", attr_name + "Autospacing")
                reasons = []
                if automatic is not None:
                    try:
                        if on_off(automatic):
                            reasons.append("automatic_spacing_not_resolved")
                    except ValueError:
                        reasons.append("property_value_unrecognized")
                observe(prop, raw, origins + auto_origins, self.number(raw, 20), "pt", reasons)
        line, origins = self.effective(layers, "pPr", "spacing", "line")
        if origins:
            mode, mode_origins = self.effective(layers, "pPr", "spacing", "lineRule")
            mode = mode or "auto"
            value = self.number(line, 240 if mode == "auto" else 20)
            observe("paragraph.line_spacing", line, origins + mode_origins,
                    value if mode == "auto" else {"mode": mode, "amount": value},
                    "multiple" if mode == "auto" else "pt",
                    ["line_rule_unrecognized"] if mode not in {"auto", "exact", "atLeast"} else [])
        for group, prop in ((("firstLineChars", "firstLine"), "paragraph.first_line_indent"),
                            (("hangingChars", "hanging"), "paragraph.hanging_indent"),
                            (("leftChars", "left"), "paragraph.left_indent"),
                            (("rightChars", "right"), "paragraph.right_indent")):
            choices = [(name, *self.effective(layers, "pPr", "ind", name)) for name in group]
            choices = [item for item in choices if item[2]]
            if choices:
                name, raw, origins = choices[0]
                observe(prop, raw, origins, self.number(raw, 100 if name.endswith("Chars") else 20),
                        "characters" if name.endswith("Chars") else "pt",
                        ["indent_units_overlap"] if len(choices) > 1 else [])
        runs = p.xpath(".//w:r[not(ancestor::w:del) and not(ancestor::w:txbxContent)]", namespaces=NS)
        for index, run in enumerate(runs, start=1):
            run_text = text_of(run)
            if run_text.strip():
                self.run(p, run, part, role, basis, region, table_style=table_style,
                         run=index, **indices)

    def effective_on_off(self, layers, kind, name):
        found = []
        for layer in layers:
            node = self.property_node(layer, kind, name)
            if node is not None:
                raw = attr(node, "val", "true")
                found.append((raw, self.origin(node, layer, raw)))
        return (found[-1][0], [item[1] for item in found]) if found else (None, [])

    @staticmethod
    def number(raw, divisor):
        try:
            value = float(raw) / divisor
            return round(value, 6) if math.isfinite(value) else None
        except (ValueError, TypeError):
            return None

    def run(self, p, r, part, role, basis, region, *, table_style=None, **indices):
        layers, bad = self.layers(p, r, table_style)
        layers[-1] = _Layer(r, part, "direct")
        hidden, _ = self.effective_on_off(layers, "rPr", "vanish")
        if hidden not in {None, "false", "0", "off"} or r.xpath("ancestor::w:ins|w:rPr/w:rPrChange", namespaces=NS):
            region = "context_only"
        location = self.location(r, part, **indices)
        excerpt = text_of(r)
        slots = []
        if re.search(r"[\u2e80-\ua4cf\uac00-\ud7ff\uf900-\ufaff]", excerpt):
            slots.append(("eastAsia", "chinese"))
        if any(ord(char) < 128 and char.isalnum() for char in excerpt):
            slots.append(("ascii", "latin"))
        if any(128 <= ord(char) < 0x590 and char.isalpha() for char in excerpt):
            slots.append(("hAnsi", "latin_extended"))
        if re.search(r"[\u0590-\u08ff]", excerpt):
            slots.append(("cs", "complex_script"))
        for slot, scope in slots:
            selected, origins = None, []
            for layer in layers:
                node = self.property_node(layer, "rPr", "rFonts")
                if node is None:
                    continue
                theme_attr = "cstheme" if slot == "cs" else slot + "Theme"
                # A later literal attribute overrides an inherited theme; a
                # theme on the same rFonts element has precedence in Word.
                if attr(node, theme_attr) is not None:
                    selected = ("theme", attr(node, theme_attr))
                    origins.append(self.origin(node, layer, selected[1], theme_attr))
                elif attr(node, slot) is not None:
                    selected = ("literal", attr(node, slot))
                    origins.append(self.origin(node, layer, selected[1], slot))
            if selected:
                value = selected[1]
                reasons = []
                if not value:
                    reasons.append("property_value_unrecognized")
                if selected[0] == "theme":
                    value, theme_origins = self.theme_font(value, slot, layers)
                    origins += theme_origins
                    if not value:
                        reasons.append("theme_font_unresolved")
                if bad and origins[0].layer != "direct" and not any(origin.layer == "direct" for origin in origins):
                    reasons.append("style_context_unresolved")
                self.emit(location, role, basis, region, "font.family", value, None, origins,
                          excerpt=excerpt, scope=scope, reasons=reasons)
        property_slots = [scope for _, scope in slots if scope != "complex_script"]
        if not slots:
            property_slots = ["all"]
        properties = [(name, prop, divisor, property_slots) for name, prop, divisor in
                      (("sz", "font.size", 2), ("b", "font.bold", None), ("i", "font.italic", None))]
        if any(scope == "complex_script" for _, scope in slots):
            properties += [(name, prop, divisor, ["complex_script"]) for name, prop, divisor in
                           (("szCs", "font.size", 2), ("bCs", "font.bold", None), ("iCs", "font.italic", None))]
        for name, prop, divisor, scopes in properties:
            raw, origins = (self.effective(layers, "rPr", name) if divisor else self.effective_on_off(layers, "rPr", name))
            if not origins:
                continue
            reasons = []
            try:
                value = self.number(raw, divisor) if divisor else on_off(raw)
            except ValueError:
                value = None
            if value is None or divisor and value <= 0:
                reasons.append("property_value_unrecognized")
            if bad and origins[-1].layer != "direct":
                reasons.append("style_context_unresolved")
            if not divisor and origins[-1].layer != "direct" and len(origins) > 1:
                reasons.append("toggle_style_hierarchy_unresolved")
            for scope in scopes:
                self.emit(location, role, basis, region, prop, value, "pt" if divisor else None,
                          origins, excerpt=excerpt, scope=scope, reasons=reasons)

    def theme_font(self, reference, slot, layers):
        if self.theme is None or not re.fullmatch(r"(?:major|minor)(?:Ascii|HAnsi|EastAsia|Bidi)", reference):
            return None, []
        family = "majorFont" if reference.startswith("major") else "minorFont"
        script = "ea" if slot == "eastAsia" else "cs" if slot == "cs" else "latin"
        root = self.theme.find(f"a:themeElements/a:fontScheme/a:{family}", NS)
        if root is None:
            return None, []
        node = root.find("a:" + script, NS)
        if node is None:
            return None, []
        value = node.get("typeface")
        language_origins = []
        if not value and slot == "eastAsia":
            language, language_origins = self.effective(layers, "rPr", "lang", "eastAsia")
            language_script = {"zh-CN": "Hans", "zh-SG": "Hans", "zh-TW": "Hant", "zh-HK": "Hant", "ja-JP": "Jpan", "ko-KR": "Hang"}.get(language)
            if language_script:
                matches = root.xpath("a:font[@script=$script]", namespaces=NS, script=language_script)
                if matches:
                    node, value = matches[0], matches[0].get("typeface")
        origin = TemplatePropertyOrigin(part=self.theme_part, xpath=node.getroottree().getpath(node) + "/@typeface",
                                        layer="theme", raw_value=value or "", node_sha256=hashlib.sha256(etree.tostring(node, method="c14n")).hexdigest())
        return value or None, language_origins + [origin]

    def section(self, sect, index, region):
        part = "word/document.xml"
        layer = _Layer(sect, part, "section")
        location = self.location(sect, part, section=index)
        for name, prop in (("top", "top"), ("bottom", "bottom"), ("left", "left"), ("right", "right"), ("gutter", "gutter"), ("header", "header_distance"), ("footer", "footer_distance")):
            node = sect.find(tag("pgMar"))
            raw = attr(node, name)
            if raw is not None:
                self.emit(location, "page", "section_properties", region, "page.margin." + prop,
                          self.number(raw, 1440 / 2.54), "cm", [self.origin(node, layer, raw, name)],
                          reasons=["property_value_unrecognized"] if self.number(raw, 1440 / 2.54) is None else [])
        size = sect.find(tag("pgSz"))
        width, height = attr(size, "w"), attr(size, "h")
        if width and height:
            dimensions = {"width_cm": self.number(width, 1440 / 2.54), "height_cm": self.number(height, 1440 / 2.54)}
            origins = [self.origin(size, layer, width, "w"), self.origin(size, layer, height, "h")]
            self.emit(location, "page", "section_properties", region, "page.dimensions", dimensions, "cm", origins,
                      reasons=["property_value_unrecognized"] if any(value is None or value <= 0 for value in dimensions.values()) else [])
            if all(value is not None for value in dimensions.values()) and abs(min(dimensions.values()) - 21) < 0.05 and abs(max(dimensions.values()) - 29.7) < 0.05:
                self.emit(location, "page", "section_properties", region, "page.paper_size", "A4", None, origins)
        for node_name, attribute, prop, normalize in (
            ("pgSz", "orient", "page.orientation", lambda value: value if value in {"portrait", "landscape"} else None),
            ("pgNumType", "fmt", "page_number.number_format", lambda value: {"decimal": "arabic", "lowerRoman": "lower_roman", "upperRoman": "upper_roman"}.get(value)),
            ("pgNumType", "start", "page_number.start", lambda value: int(value) if value.isdigit() else None),
            ("cols", "num", "section.column_count", lambda value: int(value) if value.isdigit() else None),
            ("textDirection", "val", "section.text_direction", lambda value: {"lrTb": "horizontal", "tbRl": "vertical", "tbRlV": "vertical"}.get(value)),
        ):
            node = sect.find(tag(node_name))
            raw = attr(node, attribute)
            if raw is not None:
                value = normalize(raw)
                self.emit(location, "page_number" if prop.startswith("page_number.") else "page", "section_properties", region,
                          prop, value, None, [self.origin(node, layer, raw, attribute)],
                          reasons=["property_value_unrecognized"] if value is None else [])
        if not hasattr(self, "inherited_headers"):
            self.inherited_headers = {}
        for kind in ("header", "footer"):
            for reference in sect.findall(tag(kind + "Reference")):
                variant = attr(reference, "type", "default")
                target = self.relationships.get(reference.get(f"{{{R}}}id"))
                if target:
                    self.inherited_headers[(kind, variant)] = target
                else:
                    self.diagnostic("header_footer_reference_unresolved", "页眉页脚引用不可读取。", location)
            for (current_kind, variant), target in self.inherited_headers.items():
                if current_kind != kind:
                    continue
                root = self.parts[target]
                for pindex, p in enumerate(root.findall(tag("p")), start=1):
                    if text_of(p).strip():
                        self.paragraph(p, target, kind, f"section_{variant}_{kind}", region,
                                       section=index, paragraph=pindex)
                for instruction in root.findall(".//" + tag("instrText")):
                    match = re.search(r"\bPAGE\b(?:\s+\\\*\s+(roman|ROMAN|Arabic))?", instruction.text or "")
                    if match:
                        field_location = self.location(instruction, target, section=index)
                        self.emit(field_location, kind, "page_field_instruction", region, kind + ".field_type", "PAGE", None,
                                  [self.origin(instruction, _Layer(instruction, target, "direct"), instruction.text or "")])

    def table(self, tbl, index, section, region):
        part = "word/document.xml"
        sid = attr(tbl.find("w:tblPr/w:tblStyle", NS), "val", self.defaults.get("table"))
        chain, bad = self.style_chain(sid, "table")
        layers = [_Layer(style, "word/styles.xml", "table_style", attr(style, "styleId")) for style in chain] + [_Layer(tbl, part, "direct")]
        conditional = any(style.findall(tag("tblStylePr")) for style in chain)
        if conditional:
            self.diagnostic("conditional_table_style_unresolved", "表格含条件样式；未直接指定的单元格有效版式尚不能确定。", self.location(tbl, part, table=index, section=section))
        borders, origins = {}, []
        for layer in layers:
            node = layer.node.find("w:tblPr/w:tblBorders", NS)
            if node is not None:
                for edge in node:
                    name = etree.QName(edge).localname
                    borders[name] = {"style": attr(edge, "val"), "width_pt": self.number(attr(edge, "sz"), 8), "color": attr(edge, "color")}
                    origins.append(self.origin(edge, layer, json.dumps(borders[name], ensure_ascii=False)))
        if origins:
            self.emit(self.location(tbl, part, table=index, section=section), "table", "table_element", region,
                      "table.borders", borders, None, origins, reasons=["table_style_context_unresolved"] if bad or conditional else [])
            # Only classify complete, simple grids. Cell overrides, merged cells
            # and conditional styles require edge resolution beyond this reader.
            edges = {name: borders.get(name, {}).get("style") for name in ("top", "bottom", "left", "right", "insideH", "insideV")}
            absent = {"nil", "none"}
            has_overrides = bool(tbl.xpath(".//w:tcBorders|.//w:gridSpan|.//w:vMerge", namespaces=NS))
            border_style = None
            if not bad and not conditional and not has_overrides:
                if all(value in absent for value in edges.values()):
                    border_style = "none"
                elif all(value is not None and value not in absent for value in edges.values()):
                    border_style = "all_borders"
            self.emit(self.location(tbl, part, table=index, section=section), "table", "complete_border_grid", region,
                      "table.border_style", border_style, None, origins,
                      reasons=[] if border_style else ["border_grid_classification_unresolved"])
        for row_index, row in enumerate(tbl.findall(tag("tr")), start=1):
            header = row.find("w:trPr/w:tblHeader", NS)
            is_header = header is not None and attr(header, "val", "true") in {"true", "1", "on"}
            for col_index, cell in enumerate(row.findall(tag("tc")), start=1):
                indices = dict(table=index, section=section, row=row_index, column=col_index)
                cb = cell.find("w:tcPr/w:tcBorders", NS)
                if cb is not None:
                    values = {etree.QName(edge).localname: {"style": attr(edge, "val"), "width_pt": self.number(attr(edge, "sz"), 8)} for edge in cb}
                    self.emit(self.location(cell, part, **indices), "table_cell", "cell_properties", region, "table.cell_borders", values, None,
                              [self.origin(cb, _Layer(cell, part, "direct"), json.dumps(values, ensure_ascii=False))])
                for pindex, p in enumerate(cell.findall(tag("p")), start=1):
                    role = "table_header" if is_header else "table_body" if row_index > 1 else "table_cell"
                    self.paragraph(p, part, role, "repeating_header_flag" if is_header else "table_row_candidate", region,
                                   table_style=sid, paragraph=pindex, **indices)
                if cell.find(tag("tbl")) is not None:
                    self.diagnostic("nested_table_layout_not_resolved", "嵌套表格版式尚未解析。", self.location(cell, part, **indices))
