"""Deterministic PDF evidence -> exact academic DOCX character ranges.

Only renderer line breaks and whitespace widths may differ. Letters, case,
punctuation and Unicode forms are never guessed, transliterated or fuzzed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .feedback_contracts import (
    DocxTextRange, FeedbackRecord, FeedbackVersionContext, SelectionAnchor,
    SelectionHint, SelectionResolution, TargetCandidate, content_hash, seal_contract,
)
from .feedback_store import FeedbackError
from .selection_indexes import DocxParagraph, DocxSelectionIndex, PdfPage, PdfSelectionIndex

ALGORITHM = "selection-resolver/1.0"


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _slice(value: str, start: int, end: int) -> str:
    raw = value.encode("utf-16-le")
    if start < 0 or end < start or end * 2 > len(raw):
        raise FeedbackError("needs_user_input", "选区字符偏移超出可信 PDF 文字层。")
    try:
        return raw[start * 2:end * 2].decode("utf-16-le")
    except UnicodeDecodeError as error:
        raise FeedbackError("needs_user_input", "选区不能拆开一个 Unicode 字符，请重新选择。") from error


def _page_text(page: PdfPage, *, lines: bool) -> str:
    return "".join(item.text + ("\n" if lines and item.has_eol else "") for item in page.items)


@dataclass(frozen=True)
class PdfEvidence:
    selected_text: str
    before: str
    after: str


def verify_hint(hint: SelectionHint, context: FeedbackVersionContext, index: PdfSelectionIndex) -> PdfEvidence:
    if index.pdf_sha256 != context.preview_pdf_sha256 or index.page_count != context.page_count:
        raise FeedbackError("stale_preview", "文字层索引不属于此预览。")
    pages = {page.page: page for page in index.pages}
    if (len(pages) != len(index.pages) or set(pages) != {span.page for span in hint.spans}
            or any([item.index for item in page.items] != list(range(len(page.items))) for page in pages.values())):
        raise FeedbackError("validation_failed", "PDF 文字层的项目身份无法通过校验。")
    parts, contexts = [], []
    previous = None
    for span in hint.spans:
        page = pages[span.page]
        if span.end_item >= len(page.items) or span.start_item >= len(page.items):
            raise FeedbackError("needs_user_input", "选区项目超出可信 PDF 文字层。")
        first, last = page.items[span.start_item], page.items[span.end_item]
        _slice(first.text, span.start_offset_utf16, utf16_length(first.text))
        _slice(last.text, 0, span.end_offset_utf16)
        if span.start_item == span.end_item:
            selected = _slice(first.text, span.start_offset_utf16, span.end_offset_utf16)
        else:
            selected = _slice(first.text, span.start_offset_utf16, utf16_length(first.text)) + ("\n" if first.has_eol else "")
            selected += "".join(item.text + ("\n" if item.has_eol else "") for item in page.items[span.start_item + 1:span.end_item])
            selected += _slice(last.text, 0, span.end_offset_utf16)
        before_lines = _page_text(PdfPage(page=page.page, items=page.items[:span.start_item]), lines=True) + _slice(first.text, 0, span.start_offset_utf16)
        after_lines = _slice(last.text, span.end_offset_utf16, utf16_length(last.text)) + ("\n" if last.has_eol else "") + _page_text(PdfPage(page=page.page, items=page.items[span.end_item + 1:]), lines=True)
        before_compact = "".join(item.text for item in page.items[:span.start_item]) + _slice(first.text, 0, span.start_offset_utf16)
        after_compact = _slice(last.text, span.end_offset_utf16, utf16_length(last.text)) + "".join(item.text for item in page.items[span.end_item + 1:])
        if previous is not None:
            prior_span, prior_page = previous
            if (span.page != prior_span.page + 1 or before_lines.strip() or
                    (_slice(prior_page.items[prior_span.end_item].text, prior_span.end_offset_utf16,
                            utf16_length(prior_page.items[prior_span.end_item].text)) +
                     _page_text(PdfPage(page=prior_page.page, items=prior_page.items[prior_span.end_item + 1:]), lines=True)).strip()):
                raise FeedbackError("needs_user_input", "当前只支持连续选区；请分别提交不相连的位置。")
        parts.append(selected)
        contexts.append((before_lines, after_lines, before_compact, after_compact))
        previous = span, page
    selected = "\n".join(parts)
    if selected != hint.selected_text:
        raise FeedbackError("needs_user_input", "选中文字与可信 PDF 文字层跨度不一致，请重新选择。")
    before, _, old_before, _ = contexts[0]
    _, after, _, old_after = contexts[-1]
    if (hint.context_before and not any(value.endswith(hint.context_before) for value in (before, old_before)) or
            hint.context_after and not any(value.startswith(hint.context_after) for value in (after, old_after))):
        raise FeedbackError("needs_user_input", "选区前后文与可信 PDF 文字层不一致。")
    return PdfEvidence(selected, before[-256:], after[:256])


def _skeleton(text: str) -> tuple[str, list[int]]:
    positions = [index for index, char in enumerate(text) if not char.isspace()]
    return "".join(text[index] for index in positions), positions


def _gaps_compatible(pdf: str, docx: str) -> bool:
    letters, p = _skeleton(pdf)
    other, d = _skeleton(docx)
    if letters != other:
        return False
    for i in range(1, len(p)):
        pdf_gap, docx_gap = pdf[p[i - 1] + 1:p[i]], docx[d[i - 1] + 1:d[i]]
        if "\n" in pdf_gap or "\r" in pdf_gap:
            continue  # a verified renderer wrap may be within or between words/paragraphs
        if "\n" in docx_gap or "\r" in docx_gap or bool(pdf_gap) != bool(docx_gap):
            return False
    return True


def _context_matches(pdf: str, docx: str, *, suffix: bool) -> bool:
    needle, _ = _skeleton(pdf)
    letters, positions = _skeleton(docx)
    if not needle or not (letters.endswith(needle) if suffix else letters.startswith(needle)):
        return False
    begin = len(positions) - len(needle) if suffix else 0
    return _gaps_compatible(pdf, docx[positions[begin]:positions[begin + len(needle) - 1] + 1])


@dataclass(frozen=True)
class Match:
    candidate: TargetCandidate
    ranges: list[DocxTextRange]
    supported: bool
    before: str
    after: str
    requires_confirmation: bool = False


def find_matches(index: DocxSelectionIndex, evidence: PdfEvidence, context: FeedbackVersionContext) -> list[Match]:
    if index.sha256 != context.base_docx_sha256:
        raise FeedbackError("stale_base_version", "语义索引不属于所选 DOCX 版本。")
    if (len({p.object_id for p in index.paragraphs}) != len(index.paragraphs) or
            sum(len(p.text) for p in index.paragraphs) > 2000000):
        raise FeedbackError("validation_failed", "DOCX 文本索引身份或大小无法通过校验。")
    stories: dict[str, list[DocxParagraph]] = {}
    for paragraph in index.paragraphs:
        stories.setdefault(paragraph.story_id, []).append(paragraph)
    needle, _ = _skeleton(evidence.selected_text)
    matches = []
    for paragraphs in stories.values():
        # Empty unsafe paragraphs remain barriers; a pure page-break paragraph
        # is a safe separator in the index and can occur in cross-page selection.
        segments = [p.text if p.text or p.editable else "\0" for p in paragraphs]
        text = "\n".join(segments)
        skeleton, positions = _skeleton(text)
        starts, cursor = [], 0
        for segment in segments:
            starts.append(cursor); cursor += len(segment) + 1
        offset = 0
        while needle and (hit := skeleton.find(needle, offset)) >= 0:
            offset = hit + 1
            start, end = positions[hit], positions[hit + len(needle) - 1] + 1
            # Preserve explicitly selected leading/trailing spaces within their
            # paragraph. Do not add characters beyond the verified selection.
            leading = len(evidence.selected_text) - len(evidence.selected_text.lstrip())
            trailing = len(evidence.selected_text) - len(evidence.selected_text.rstrip())
            start -= min(leading, start - (text.rfind("\n", 0, start) + 1))
            following = text.find("\n", end)
            end += min(trailing, (len(text) if following < 0 else following) - end)
            if not _gaps_compatible(evidence.selected_text, text[start:end]):
                continue
            ranges, supported, labels, special_story = [], True, [], False
            for paragraph, origin in zip(paragraphs, starts):
                a, b = max(0, start - origin), min(len(paragraph.text), end - origin)
                if a >= b:
                    continue
                value = paragraph.text[a:b]
                if len(value) > 4096:
                    raise FeedbackError("needs_user_input", "映射到 DOCX 的文字范围过长，请缩小选区。")
                ranges.append(DocxTextRange(object_id=paragraph.object_id, start_utf16=utf16_length(paragraph.text[:a]),
                    length_utf16=utf16_length(value), matched_text=value))
                supported &= paragraph.editable
                special_story |= paragraph.semantic_role in {"header", "footer", "footnote", "endnote"}
                labels.append(paragraph.location_label)
            if not ranges:
                continue
            candidate = TargetCandidate(candidate_id=content_hash({"algorithm": ALGORITHM, "context": context.context_id,
                "ranges": [span.model_dump(mode="json") for span in ranges]}), object_id=ranges[0].object_id,
                location_label=labels[0] if len(labels) == 1 else f"{labels[0]} 至 {labels[-1]}",
                excerpt=(text[max(0, start - 48):start] + "「" + text[start:end][:3900] +
                         ("…" if end - start > 3900 else "") + "」" + text[end:end + 48]))
            matches.append(Match(candidate, ranges, supported and len(ranges) <= 64,
                                 text[max(0, start - 4096):start], text[end:end + 4096],
                                 len(ranges) > 1 or special_story))
            if len(matches) > 256:
                raise FeedbackError("needs_user_input", "匹配位置过多，请选择更多前后文后重新提交。")
    # Context comes from the trusted PDF index, never a client disambiguation claim.
    before, after = evidence.before, evidence.after
    filters = []
    if before:
        subset = {match.candidate.candidate_id for match in matches if _context_matches(before, match.before, suffix=True)}
        if subset: filters.append(subset)
    if after:
        subset = {match.candidate.candidate_id for match in matches if _context_matches(after, match.after, suffix=False)}
        if subset: filters.append(subset)
    if filters:
        allowed = set.intersection(*filters)
        if allowed:
            matches = [match for match in matches if match.candidate.candidate_id in allowed]
        # Conflicting before/after evidence must not silently choose either side.
        elif len(matches) == 1:
            return []
    return matches


def resolution(record: FeedbackRecord, context: FeedbackVersionContext, matches: list[Match], *, chosen: str | None = None) -> SelectionResolution:
    hint = record.submission.selection
    payload = dict(schema_version="selection-resolution/1.0", feedback_id=record.feedback_id, version_context_id=context.context_id)
    anchor = None
    candidates = []
    if hint is None:
        status, reason = "needs_user_input", "此反馈没有选区；全文需求或咨询将由后续解析处理。"
    elif not matches:
        status, reason = "needs_user_input", "未找到可验证的 DOCX 文本范围，请选择更多文字或缩小范围。"
    elif any(not match.supported for match in matches):
        status, reason = "unsupported_target", "匹配范围涉及字段、隐藏或修订文字等不可靠结构，请改选普通文本。"
    elif chosen is None and (len(matches) > 1 or matches[0].requires_confirmation or len(hint.spans) > 1):
        status = "ambiguous"
        reason = "相同文字对应多个位置，请核对上下文并选择目标。" if len(matches) > 1 else "选区跨段、跨页或位于注释、页眉页脚，请核对目标位置后确认。"
        candidates = [match.candidate for match in matches]
    else:
        match = next((match for match in matches if match.candidate.candidate_id == chosen), None) if chosen else matches[0]
        if match is None:
            raise FeedbackError("needs_user_input", "只能选择当前展示的目标候选。")
        anchor = seal_contract(SelectionAnchor, dict(schema_version="selection-anchor/1.1",
            task_id=context.task_id, base_version_id=context.base_version_id, base_docx_sha256=context.base_docx_sha256,
            preview_artifact_id=context.preview_artifact_id, preview_pdf_sha256=context.preview_pdf_sha256,
            renderer_id=context.renderer_id, renderer_version=context.renderer_version, selection=hint,
            ranges=match.ranges, status="ready"), "anchor_id")
        status, reason = "ready", "目标已按用户选择确认，尚未执行修改。" if chosen else "已验证 PDF 选区并定位到唯一 DOCX 范围，尚未执行修改。"
    return seal_contract(SelectionResolution, dict(**payload, status=status, anchor=anchor, candidates=candidates, reason=reason), "resolution_id")
