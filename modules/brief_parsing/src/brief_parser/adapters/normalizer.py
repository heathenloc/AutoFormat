"""Meaning-preserving Unicode and whitespace normalization with raw mappings."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from unicodedata import normalize

from brief_parser.domain.document import (
    NormalizationKind,
    NormalizationMap,
    NormalizationSpan,
)


@dataclass(frozen=True, slots=True)
class _MappedChar:
    value: str
    raw_start: int
    raw_end: int
    kind: NormalizationKind


class TextNormalizer:
    """Normalize for search while retaining Unicode code-point provenance."""

    def normalize(
        self,
        raw_text: str,
        *,
        source_id: str,
        block_id: str,
    ) -> tuple[str, NormalizationMap]:
        newline_normalized = self._normalize_newlines(raw_text)
        nfc_normalized = self._normalize_nfc(newline_normalized)
        collapsed = self._collapse_whitespace(nfc_normalized)
        normalized_text = "".join(item.value for item in collapsed)
        spans = self._to_spans(collapsed)
        fingerprint = "|".join(
            [
                source_id,
                block_id,
                raw_text,
                normalized_text,
                *(
                    f"{span.normalized_start}:{span.normalized_end}:"
                    f"{span.raw_start}:{span.raw_end}:{span.kind.value}"
                    for span in spans
                ),
            ]
        )
        normalization_map_id = f"nmap_{sha256(fingerprint.encode('utf-8')).hexdigest()[:24]}"
        mapping = NormalizationMap(
            normalization_map_id=normalization_map_id,
            source_id=source_id,
            block_id=block_id,
            raw_length=len(raw_text),
            normalized_length=len(normalized_text),
            spans=spans,
        )
        return normalized_text, mapping

    def _normalize_newlines(self, raw_text: str) -> list[_MappedChar]:
        result: list[_MappedChar] = []
        index = 0
        while index < len(raw_text):
            char = raw_text[index]
            if char == "\r":
                is_crlf = index + 1 < len(raw_text) and raw_text[index + 1] == "\n"
                raw_end = index + 2 if is_crlf else index + 1
                result.append(
                    _MappedChar("\n", index, raw_end, NormalizationKind.NORMALIZED)
                )
                index = raw_end
                continue
            result.append(
                _MappedChar(char, index, index + 1, NormalizationKind.IDENTITY)
            )
            index += 1
        return result

    def _normalize_nfc(self, source: list[_MappedChar]) -> list[_MappedChar]:
        source_text = "".join(item.value for item in source)
        normalized_text = normalize("NFC", source_text)
        if source_text == normalized_text:
            return source

        result: list[_MappedChar] = []
        matcher = SequenceMatcher(a=source_text, b=normalized_text, autojunk=False)
        for operation, source_start, source_end, target_start, target_end in matcher.get_opcodes():
            if operation == "equal":
                result.extend(source[source_start:source_end])
                continue
            if operation == "delete":
                continue
            if source_start < source_end:
                raw_start = min(item.raw_start for item in source[source_start:source_end])
                raw_end = max(item.raw_end for item in source[source_start:source_end])
            elif source:
                anchor = source[min(source_start, len(source) - 1)]
                raw_start, raw_end = anchor.raw_start, anchor.raw_end
            else:
                continue
            for char in normalized_text[target_start:target_end]:
                result.append(
                    _MappedChar(char, raw_start, raw_end, NormalizationKind.NORMALIZED)
                )
        return result

    def _collapse_whitespace(self, source: list[_MappedChar]) -> list[_MappedChar]:
        result: list[_MappedChar] = []
        index = 0
        while index < len(source):
            item = source[index]
            if not item.value.isspace():
                result.append(item)
                index += 1
                continue
            run = [item]
            index += 1
            while index < len(source) and source[index].value.isspace():
                run.append(source[index])
                index += 1
            raw_start = min(part.raw_start for part in run)
            raw_end = max(part.raw_end for part in run)
            kind = (
                NormalizationKind.IDENTITY
                if len(run) == 1
                and run[0].value == " "
                and run[0].kind == NormalizationKind.IDENTITY
                else NormalizationKind.COLLAPSED_WHITESPACE
            )
            result.append(_MappedChar(" ", raw_start, raw_end, kind))
        return result

    def _to_spans(self, chars: list[_MappedChar]) -> list[NormalizationSpan]:
        spans: list[NormalizationSpan] = []
        for index, item in enumerate(chars):
            candidate = NormalizationSpan(
                normalized_start=index,
                normalized_end=index + 1,
                raw_start=item.raw_start,
                raw_end=item.raw_end,
                kind=item.kind,
            )
            if (
                spans
                and spans[-1].kind == candidate.kind
                and spans[-1].normalized_end == candidate.normalized_start
                and spans[-1].raw_end == candidate.raw_start
            ):
                previous = spans.pop()
                spans.append(
                    NormalizationSpan(
                        normalized_start=previous.normalized_start,
                        normalized_end=candidate.normalized_end,
                        raw_start=previous.raw_start,
                        raw_end=candidate.raw_end,
                        kind=candidate.kind,
                    )
                )
            else:
                spans.append(candidate)
        return spans
