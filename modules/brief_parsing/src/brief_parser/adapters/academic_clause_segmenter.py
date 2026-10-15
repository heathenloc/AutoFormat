"""Split mixed format/content clauses before sending academic text to models."""

from __future__ import annotations

import re

from brief_parser.academic_source_policy import PROPERTY_CUES, format_properties, scope_match
from brief_parser.adapters.clause_segmenter import ClauseSegmenter


class AcademicClauseSegmenter(ClauseSegmenter):
    def _ranges(self, text: str) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for start, end in super()._ranges(text):
            fragment = text[start:end]
            if not scope_match(fragment) or not format_properties(fragment):
                result.append((start, end))
                continue
            # Delimiters stay in their original spans; normalized/raw offsets
            # and quote hashes continue to be checked by EvidenceIndexBuilder.
            cuts = [start] + [start + match.end() for match in re.finditer(r"[，,]|(?<!\d)\.\s+", fragment)] + [end]
            # Handle adjacent count/style statements without punctuation.
            extra = []
            for left, right in zip(cuts, cuts[1:]):
                part = text[left:right]
                excluded_match = scope_match(part)
                format_matches = [match for _, pattern in PROPERTY_CUES if (match := pattern.search(part))]
                if excluded_match is None or not format_matches:
                    continue
                first_format = min(match.start() for match in format_matches)
                if first_format > 0 and scope_match(part[:first_format]) and not scope_match(part[first_format:]):
                    extra.append(left + first_format)
                elif excluded_match.start() > first_format and not scope_match(part[:excluded_match.start()]):
                    extra.append(left + excluded_match.start())
            cuts = sorted(set(cuts + extra))
            groups: list[tuple[int, int, bool]] = []
            for left, right in zip(cuts, cuts[1:]):
                trimmed = self._trim(text, left, right)
                if trimmed is None:
                    continue
                left, right = trimmed
                excluded = bool(scope_match(text[left:right]))
                if groups and groups[-1][2] == excluded:
                    groups[-1] = (groups[-1][0], right, excluded)
                else:
                    groups.append((left, right, excluded))
            result.extend((left, right) for left, right, _ in groups)
        return result
