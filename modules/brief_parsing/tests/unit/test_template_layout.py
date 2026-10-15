"""Logical DOCX observations preserve authority, inheritance and source bytes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.adapters.template_layout import DocxTemplateLayoutReader, NS, tag
from brief_parser.application.service import ParseServiceRequest
from brief_parser.bootstrap import build_service
from brief_parser.compilers.template_layout import build_template_groups
from brief_parser.compilers.academic_common import AcademicCommonFormatExtractor
from brief_parser.config import Settings
from brief_parser.domain.academic_bundle import AcademicParseBundle
from lxml import etree
from tests.unit.test_academic_common import _ir_from_docx


ROOT = Path(__file__).resolve().parents[4]


def _source(tmp_path: Path, body: str, *, styles: str = "", extras=None):
    document = Document()
    buffer = BytesIO()
    document.save(buffer)
    base = f'<w:document xmlns:w="{NS["w"]}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>{body}</w:body></w:document>'
    replacements = {"word/document.xml": base.encode()}
    if styles:
        replacements["word/styles.xml"] = f'<w:styles xmlns:w="{NS["w"]}">{styles}</w:styles>'.encode()
    replacements.update(extras or {})
    output = BytesIO()
    with ZipFile(buffer) as archive, ZipFile(output, "w", ZIP_DEFLATED) as destination:
        for item in archive.infolist():
            destination.writestr(item.filename, replacements.pop(item.filename, archive.read(item.filename)))
        for name, data in replacements.items():
            destination.writestr(name, data)
    path = tmp_path / "论文模板.docx"
    path.write_bytes(output.getvalue())
    return FileSecurityValidator().secure_file(path, source_id="src_001", client_source_id="brief"), path


def _p(text="正文样例 A12", ppr="", rpr=""):
    return f'<w:p><w:pPr>{ppr}</w:pPr><w:r><w:rPr>{rpr}</w:rPr><w:t>{text}</w:t></w:r></w:p>'


def _observations(result, prop, *, role=None, paragraph=None):
    return [item for item in result.observations if item.property_id == prop
            and (role is None or item.semantic_role == role)
            and (paragraph is None or item.location.paragraph == paragraph)]


def test_geometry_paragraph_units_and_immutable_provenance(tmp_path):
    body = _p(ppr='<w:spacing w:before="120" w:after="240" w:line="360" w:lineRule="auto"/><w:ind w:firstLineChars="200"/>')
    body += '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:bottom="1417" w:left="1417" w:right="1417"/></w:sectPr>'
    source, path = _source(tmp_path, body)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = DocxTemplateLayoutReader().read((source,))
    assert _observations(result, "paragraph.spacing_before")[0].value == 6
    assert _observations(result, "paragraph.spacing_after")[0].value == 12
    assert _observations(result, "paragraph.line_spacing")[0].value == 1.5
    assert _observations(result, "paragraph.first_line_indent")[0].value == 2
    assert _observations(result, "page.paper_size")[0].value == "A4"
    assert _observations(result, "page.margin.top")[0].value == pytest.approx(2.5, abs=.01)
    for item in result.observations:
        assert item.status == "pending_confirmation" and item.source_kind == "template_observation"
        assert item.source_sha256 == digest
        assert item.location.xpath and item.origins[0].node_sha256
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_style_chain_and_direct_overrides_are_observed_with_origins(tmp_path):
    styles = '<w:style w:type="paragraph" w:styleId="Base"><w:pPr><w:jc w:val="both"/></w:pPr><w:rPr><w:sz w:val="24"/><w:rFonts w:eastAsia="宋体" w:ascii="Times New Roman"/></w:rPr></w:style>'
    styles += '<w:style w:type="paragraph" w:styleId="Child"><w:basedOn w:val="Base"/><w:rPr><w:sz w:val="28"/></w:rPr></w:style>'
    source, _ = _source(tmp_path, _p(ppr='<w:pStyle w:val="Child"/>', rpr='<w:sz w:val="21"/>'), styles=styles)
    result = DocxTemplateLayoutReader().read((source,))
    size = _observations(result, "font.size")[0]
    assert size.value == 10.5
    assert [item.style_id for item in size.origins] == ["Base", "Child", None]
    assert _observations(result, "paragraph.alignment")[0].value == "both"
    assert {(item.character_scope, item.value) for item in _observations(result, "font.family")} == {("chinese", "宋体"), ("latin", "Times New Roman"), ("digits", "Times New Roman")}


def test_theme_same_node_priority_and_later_literal_override(tmp_path):
    styles = '<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:rPr><w:rFonts w:ascii="Ignored" w:asciiTheme="minorAscii"/></w:rPr></w:style>'
    body = _p("Latin") + _p("Direct", rpr='<w:rFonts w:ascii="Courier New"/>')
    source, _ = _source(tmp_path, body, styles=styles)
    result = DocxTemplateLayoutReader().read((source,))
    themed = _observations(result, "font.family", paragraph=1)[0]
    assert themed.value == "Cambria" and themed.origins[-1].layer == "theme"
    assert _observations(result, "font.family", paragraph=2)[0].value == "Courier New"


def test_missing_theme_and_cycle_keep_unknown_values(tmp_path):
    styles = '<w:style w:type="paragraph" w:styleId="A"><w:basedOn w:val="B"/></w:style><w:style w:type="paragraph" w:styleId="B"><w:basedOn w:val="A"/></w:style>'
    source, _ = _source(tmp_path, _p(ppr='<w:pStyle w:val="A"/>', rpr='<w:rFonts w:asciiTheme="unexpectedTheme"/>'), styles=styles)
    result = DocxTemplateLayoutReader().read((source,))
    assert "style_cycle" in {item.code for item in result.diagnostics}
    assert _observations(result, "font.family")[0].resolution == "unresolved"


def test_real_heading_ends_toc_and_abstract_region(tmp_path):
    styles = '<w:style w:type="paragraph" w:styleId="T1"><w:name w:val="toc 1"/></w:style><w:style w:type="paragraph" w:styleId="H1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
    body = _p("摘要") + _p("摘要示例") + _p("目录") + _p("1 绪论", ppr='<w:pStyle w:val="T1"/>')
    body += _p("1 绪论", ppr='<w:pStyle w:val="H1"/>') + _p("正文样例")
    source, _ = _source(tmp_path, body, styles=styles)
    # Explicit size exposes a role observation for every paragraph.
    source = _with_size(source)
    result = DocxTemplateLayoutReader().read((source,))
    assert {item.location.paragraph: item.semantic_role for item in _observations(result, "font.size")} == {
        1: "abstract_heading", 2: "abstract", 3: "toc_heading", 4: "toc_heading_1", 5: "heading_1", 6: "body",
    }


def _with_size(source):
    output = BytesIO()
    with ZipFile(BytesIO(source.content)) as archive, ZipFile(output, "w", ZIP_DEFLATED) as destination:
        for item in archive.infolist():
            data = archive.read(item.filename)
            if item.filename == "word/document.xml":
                root = etree.fromstring(data)
                for node in root.findall(".//" + tag("rPr")):
                    etree.SubElement(node, tag("sz")).set(tag("val"), "24")
                data = etree.tostring(root)
            destination.writestr(item.filename, data)
    content = output.getvalue()
    return replace(source, content=content, byte_size=len(content), sha256=hashlib.sha256(content).hexdigest())


@pytest.mark.parametrize("ppr,rpr", [
    ('<w:spacing w:before="bad"/>', ''),
    ('<w:spacing w:line="nan" w:lineRule="exact"/>', ''),
    ('<w:spacing w:before="120" w:beforeAutospacing="bad"/>', ''),
    ('<w:ind w:firstLine="200" w:firstLineChars="200"/>', ''),
    ('', '<w:sz w:val="0"/>'),
    ('', '<w:b w:val="invalid"/>'),
])
def test_invalid_and_ambiguous_attributes_are_unresolved(tmp_path, ppr, rpr):
    source, _ = _source(tmp_path, _p(ppr=ppr, rpr=rpr), styles='<w:docDefaults/>')
    result = DocxTemplateLayoutReader().read((source,))
    assert result.observations and all(item.resolution == "unresolved" for item in result.observations)


def test_header_inheritance_page_field_and_footnote_locations(tmp_path):
    rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rHead" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="/word/header1.xml"/></Relationships>'
    header = f'<w:hdr xmlns:w="{NS["w"]}">{_p("大学名称", rpr="<w:sz w:val=\"20\"/>")}<w:p><w:r><w:instrText>PAGE</w:instrText></w:r></w:p></w:hdr>'.encode()
    footnote = f'<w:footnotes xmlns:w="{NS["w"]}"><w:footnote w:id="1">{_p("脚注", rpr="<w:sz w:val=\"18\"/>")}</w:footnote></w:footnotes>'.encode()
    body = _p(ppr='<w:sectPr><w:headerReference w:type="default" r:id="rHead"/></w:sectPr>') + '<w:sectPr/>'
    source, _ = _source(tmp_path, body, extras={"word/_rels/document.xml.rels": rels, "word/header1.xml": header, "word/footnotes.xml": footnote})
    result = DocxTemplateLayoutReader().read((source,))
    assert {item.location.section for item in _observations(result, "font.size", role="header")} == {1, 2}
    assert len(_observations(result, "header.field_type")) == 2
    note = _observations(result, "font.size", role="footnote")[0]
    assert note.value == 9 and note.location.part == "word/footnotes.xml" and 'footnote' in note.location.xpath
    assert not any("大学名称" == item.value for item in result.observations)


def test_table_grid_and_conditional_style_are_conservative(tmp_path):
    borders = ''.join(f'<w:{edge} w:val="single" w:sz="8"/>' for edge in ("top", "bottom", "left", "right", "insideH", "insideV"))
    table = f'<w:tbl><w:tblPr><w:tblBorders>{borders}</w:tblBorders></w:tblPr><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc>{_p("表头", rpr="<w:sz w:val=\"21\"/>")}</w:tc></w:tr></w:tbl>'
    source, _ = _source(tmp_path, table)
    result = DocxTemplateLayoutReader().read((source,))
    assert _observations(result, "table.border_style")[0].value == "all_borders"
    assert _observations(result, "font.size", role="table_header")[0].location.row == 1
    styles = '<w:style w:type="table" w:styleId="Cond"><w:rPr><w:sz w:val="24"/></w:rPr><w:tblStylePr w:type="firstRow"/></w:style>'
    source, _ = _source(tmp_path, table.replace('<w:tblPr>', '<w:tblPr><w:tblStyle w:val="Cond"/>').replace('<w:sz w:val="21"/>', ''), styles=styles)
    result = DocxTemplateLayoutReader().read((source,))
    assert _observations(result, "font.size", role="table_header")[0].resolution == "unresolved"
    assert _observations(result, "table.border_style")[0].resolution == "unresolved"


def test_limits_and_duplicate_input_identifiers(tmp_path):
    source, _ = _source(tmp_path, _p(rpr='<w:sz w:val="24"/><w:b/><w:i/>'))
    result = DocxTemplateLayoutReader(max_observations=2).read((source,))
    assert len(result.observations) == 2
    assert "observation_limit_reached" in {item.code for item in result.diagnostics}
    result = DocxTemplateLayoutReader().read((source, replace(source, source_id="src_002")))
    assert len({item.observation_id for item in result.observations}) == len(result.observations)


async def test_bundle_groups_mismatch_pending_and_historical_13(tmp_path):
    body = _p("正文：小四号。") + _p("摘要：字号。") + _p("页面：页边距2.5厘米。") + _p("摘要", rpr='<w:sz w:val="28"/>')
    body += _p("摘要示例", rpr='<w:sz w:val="28"/>') + _p("目录") + _p("正文样例", ppr='<w:pStyle w:val="Heading1"/>', rpr='<w:sz w:val="28"/>')
    body += _p(rpr='<w:sz w:val="28"/>') + '<w:sectPr><w:pgMar w:top="1417" w:bottom="1417" w:left="1417" w:right="1417"/></w:sectPr>'
    source, path = _source(tmp_path, body)
    service = build_service(Settings(environment="test", provider="fake", parser_isolation_mode="in_process"))
    bundle = await service.parse_academic(ParseServiceRequest(request_id="req_template", domain_pack_id="academic_paper", requested_task_types=("format_academic_paper",), source_paths=(path,)))
    assert bundle.bundle_version == "academic-parse-bundle/1.6"
    groups = {(item.semantic_role, item.property_id): item for item in bundle.template_layout.groups}
    assert groups[("body", "font.size")].status == "source_mismatch"
    assert groups[("abstract", "font.size")].status == "blocked_by_pending_rule"
    assert all(groups[("page", "page.margin." + side)].status == "covered_by_explicit_rule" for side in ("top", "bottom", "left", "right"))
    assert all(rule.source_kind == "brief_explicit" for rule in bundle.format_ruleset.rules)
    assert bundle.template_layout.source_profiles[0].sha256 == source.sha256
    Draft202012Validator(json.loads((ROOT / 'contracts/academic-parse-bundle/academic-parse-bundle-1.6.schema.json').read_text(encoding='utf-8'))).validate(bundle.model_dump(mode="json"))
    changed = bundle.model_dump(mode="python")
    changed["template_layout"]["groups"] = []
    with pytest.raises(ValidationError, match="template groups differ"):
        AcademicParseBundle.model_validate(changed)
    previous = bundle.model_dump(mode="python")
    previous["bundle_version"] = "academic-parse-bundle/1.3"
    previous.pop("template_layout")
    from brief_parser.compilers.academic_common_v1_3 import AcademicCommonFormatExtractor as Legacy13
    from brief_parser.compilers.academic_source_review_v1_0 import build_source_review as legacy_review
    legacy_rules = Legacy13().extract(bundle.requirement_ir)
    previous["format_ruleset"] = legacy_rules.model_dump(mode="python")
    previous["source_review"] = legacy_review(bundle.requirement_ir, legacy_rules).model_dump(mode="python")
    historical = AcademicParseBundle.model_validate(previous)
    assert "template_layout" not in historical.model_dump(mode="json")
    Draft202012Validator(json.loads((ROOT / 'contracts/academic-parse-bundle/academic-parse-bundle-1.3.schema.json').read_text(encoding='utf-8'))).validate(historical.model_dump(mode="json"))
    assert build_template_groups(bundle.template_layout.observations, bundle.format_ruleset) == bundle.template_layout.groups


def test_non_docx_and_unknown_source_never_supply_template_defaults(tmp_path):
    source = FileSecurityValidator().secure_text("正文：宋体。", source_id="src_001", client_source_id="brief")
    assert not DocxTemplateLayoutReader().read((source,)).observations
    source, _ = _source(tmp_path, _p(rpr='<w:sz w:val="24"/>'))
    source = replace(source, filename="brief.docx")
    result = DocxTemplateLayoutReader().read((source,))
    assert result.profiles[0].classification == "uncertain"
    assert all(item.region == "uncertain" for item in result.observations)


def test_hidden_revisions_and_instruction_styles_are_not_template_groups(tmp_path):
    body = _p("正文：宋体。", rpr='<w:sz w:val="32"/>') + '<w:p><w:ins>'+_p("修订样例", rpr='<w:sz w:val="32"/>').replace('<w:p><w:pPr></w:pPr>', '').replace('</w:p>', '')+'</w:ins></w:p>'
    body += _p("隐藏样例", rpr='<w:vanish/><w:sz w:val="32"/>')
    source, _ = _source(tmp_path, body)
    result = DocxTemplateLayoutReader().read((source,))
    assert all(item.region == "context_only" for item in _observations(result, "font.size"))
    assert "revision_layout_not_resolved" in {item.code for item in result.diagnostics}


def test_overlapping_latin_size_conflict_preserves_other_characters(tmp_path):
    source, _ = _source(tmp_path, _p(rpr='<w:sz w:val="28"/>'))
    result = DocxTemplateLayoutReader().read((source,))
    ir = _ir_from_docx(tmp_path, ("正文：小四号。", "英文字母：四号。"))
    rules = AcademicCommonFormatExtractor().extract(ir)
    groups = {item.character_scope: item for item in build_template_groups(result.observations, rules)
              if item.property_id == "font.size"}
    assert groups["latin"].status == "blocked_by_pending_rule"
    assert groups["chinese"].status == "source_mismatch"
    assert groups["digits"].status == "source_mismatch"
    pending_ir = _ir_from_docx(tmp_path, ("正文：小四号。", "英文字母：字号。"))
    pending_groups = {item.character_scope: item for item in build_template_groups(
        result.observations, AcademicCommonFormatExtractor().extract(pending_ir)) if item.property_id == "font.size"}
    assert pending_groups["latin"].status == "blocked_by_pending_rule"


def test_direct_body_outline_clears_inherited_heading_level(tmp_path):
    styles = '<w:style w:type="paragraph" w:styleId="H1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
    source, _ = _source(tmp_path, _p(ppr='<w:pStyle w:val="H1"/><w:outlineLvl w:val="9"/>', rpr='<w:sz w:val="24"/>'), styles=styles)
    result = DocxTemplateLayoutReader().read((source,))
    assert all(item.semantic_role == "body" for item in result.observations)


def test_ambiguous_defaults_and_unreadable_theme_produce_diagnostics(tmp_path):
    styles = '<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>'
    styles += '<w:style w:type="paragraph" w:styleId="A" w:default="1"/><w:style w:type="paragraph" w:styleId="B" w:default="1"/>'
    source, _ = _source(tmp_path, _p(), styles=styles, extras={"word/theme/theme1.xml": b'<invalid'})
    result = DocxTemplateLayoutReader().read((source,))
    assert {"part_xml_unreadable", "default_style_ambiguous"} <= {item.code for item in result.diagnostics}
    assert all(item.resolution == "unresolved" for item in _observations(result, "font.size"))
