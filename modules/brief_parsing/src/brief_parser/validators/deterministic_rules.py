"""Deterministic number, date, unit, operator, and modality rules."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from brief_parser.domain.document import ExtractedDocument, NormalizationMap
from brief_parser.domain.enums import Modality, Operator
from brief_parser.domain.foundation import (
    Clause,
    ClauseSegmentation,
    DateMention,
    DeterministicClauseAnalysis,
    ModalityMention,
    NumericKind,
    NumericMention,
    RuleSpan,
    UnitMention,
)

_ARABIC_NUMBER = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CHINESE_NUMBER = r"[零〇一二两三四五六七八九十百千万亿]+"
_NUMBER = rf"(?:{_ARABIC_NUMBER}|{_CHINESE_NUMBER})"

_UNIT_ALIASES = {
    "秒钟": "second",
    "秒": "second",
    "seconds": "second",
    "second": "second",
    "分钟": "minute",
    "minutes": "minute",
    "minute": "minute",
    "小时": "hour",
    "hours": "hour",
    "hour": "hour",
    "天": "day",
    "days": "day",
    "day": "day",
    "字符": "character",
    "汉字": "character",
    "字": "character",
    "characters": "character",
    "character": "character",
    "单词": "word",
    "词": "word",
    "words": "word",
    "word": "word",
    "页面": "page",
    "页": "page",
    "pages": "page",
    "page": "page",
    "万元": "cny_10k",
    "人民币": "cny",
    "元": "cny",
    "rmb": "cny",
    "cny": "cny",
    "percent": "percent",
    "百分比": "percent",
    "\uff05": "percent",
    "%": "percent",
    "gb": "gigabyte",
    "mb": "megabyte",
    "kb": "kilobyte",
    "个": "count",
    "条": "count",
    "篇": "count",
    "张": "count",
    "套": "count",
}
_UNIT_SOURCE = "|".join(
    re.escape(item) for item in sorted(_UNIT_ALIASES, key=len, reverse=True)
)
_UNIT_PATTERN = re.compile(_UNIT_SOURCE, re.IGNORECASE)
_RANGE_PATTERN = re.compile(
    rf"(?P<start>{_NUMBER})\s*(?:-|\u2013|\u2014|~|\uff5e|至|到)\s*"
    rf"(?P<end>{_NUMBER})\s*(?P<unit>{_UNIT_SOURCE})?",
    re.IGNORECASE,
)
_PERCENT_OF_PATTERN = re.compile(rf"百分之\s*(?P<number>{_NUMBER})")
_SINGLE_PATTERN = re.compile(
    rf"(?P<currency>[¥￥])?\s*(?P<number>{_NUMBER})\s*"
    rf"(?P<unit>{_UNIT_SOURCE})?",
    re.IGNORECASE,
)
_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(?P<year>\d{4})年\s*(?P<month>\d{1,2})月\s*(?P<day>\d{1,2})日"),
    re.compile(
        r"(?<!\d)(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})(?!\d)"
    ),
)

_MODALITY_PATTERNS: tuple[tuple[Modality, re.Pattern[str]], ...] = (
    (
        Modality.MUST,
        re.compile(
            r"不得\s*(?:超过|高于|多于|少于|低于)|不能\s*(?:超过|少于)|"
            r"不(?:高|低)于|必须|务必|须要?|需要|应当|\bmust\b|\brequired\b|\bshall\b",
            re.IGNORECASE,
        ),
    ),
    (
        Modality.MUST_NOT,
        re.compile(
            r"严禁|禁止|不得|不允许|不可|不能|切勿|\bmust\s+not\b|"
            r"\bdo\s+not\b|\bprohibited\b|\bforbidden\b",
            re.IGNORECASE,
        ),
    ),
    (
        Modality.SHOULD,
        re.compile(r"建议|最好|应该|宜|\bshould\b|\brecommended\b", re.IGNORECASE),
    ),
    (
        Modality.MAY,
        re.compile(r"可以|允许|可选|\bmay\b|\boptional\b", re.IGNORECASE),
    ),
    (
        Modality.INFORMATIONAL,
        re.compile(r"仅供参考|背景信息|\bfor\s+reference\b|\binformational\b", re.IGNORECASE),
    ),
)

_OPERATOR_PATTERNS: tuple[tuple[Operator, re.Pattern[str]], ...] = (
    (
        Operator.LTE,
        re.compile(
            r"不得超过|不能超过|不超过|不高于|最多|至多|上限|<=|≤|no more than",
            re.IGNORECASE,
        ),
    ),
    (
        Operator.GTE,
        re.compile(r"不得少于|不能少于|不少于|不低于|至少|最低|>=|≥|at least", re.IGNORECASE),
    ),
    (Operator.LT, re.compile(r"少于|小于|低于|<")),
    (Operator.GT, re.compile(r"超过|大于|高于|>")),
    (Operator.EQ, re.compile(r"等于|为|=|exactly", re.IGNORECASE)),
)

_DATE_OPERATOR_PATTERNS: tuple[tuple[Operator, re.Pattern[str]], ...] = (
    (Operator.BEFORE, re.compile(r"不晚于|截至|截止|之前|以前|\bbefore\b", re.IGNORECASE)),
    (Operator.AFTER, re.compile(r"不早于|之后|以后|\bafter\b", re.IGNORECASE)),
    (Operator.EQ, re.compile(r"日期为|时间为|定于|=|\bon\b", re.IGNORECASE)),
)


class DeterministicRuleAnalyzer:
    """Extract verifiable lexical signals without producing semantic requirements."""

    def analyze(
        self,
        document: ExtractedDocument,
        segmentation: ClauseSegmentation,
    ) -> list[DeterministicClauseAnalysis]:
        blocks = {block.block_id: block for block in document.blocks}
        analyses: list[DeterministicClauseAnalysis] = []
        for clause in segmentation.clauses:
            block = blocks[clause.block_id]
            normalization_map = document.normalization_maps[block.normalization_map_id]
            dates, date_ranges = self._dates(clause, block.raw_text, normalization_map)
            numeric = self._numbers(
                clause,
                block.raw_text,
                normalization_map,
                excluded=date_ranges,
            )
            analyses.append(
                DeterministicClauseAnalysis(
                    clause_id=clause.clause_id,
                    numeric_mentions=numeric,
                    date_mentions=dates,
                    unit_mentions=self._units(
                        clause,
                        block.raw_text,
                        normalization_map,
                    ),
                    modality_mentions=self._modalities(
                        clause,
                        block.raw_text,
                        normalization_map,
                    ),
                )
            )
        return analyses

    def _dates(
        self,
        clause: Clause,
        block_raw_text: str,
        normalization_map: NormalizationMap,
    ) -> tuple[list[DateMention], list[tuple[int, int]]]:
        results: list[DateMention] = []
        occupied: list[tuple[int, int]] = []
        for pattern in _DATE_PATTERNS:
            for match in pattern.finditer(clause.normalized_text):
                if self._overlaps(match.start(), match.end(), occupied):
                    continue
                try:
                    value = date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    )
                except ValueError:
                    continue
                span = self._span(
                    clause,
                    block_raw_text,
                    normalization_map,
                    match.start(),
                    match.end(),
                )
                results.append(
                    DateMention(
                        mention_id=self._id(
                            "date",
                            clause.clause_id,
                            match.start(),
                            match.end(),
                            value.isoformat(),
                        ),
                        value=value,
                        operator=self._date_operator(clause.normalized_text, match.start()),
                        span=span,
                    )
                )
                occupied.append((match.start(), match.end()))
        results.sort(key=lambda item: item.span.normalized_start)
        return results, occupied

    def _numbers(
        self,
        clause: Clause,
        block_raw_text: str,
        normalization_map: NormalizationMap,
        *,
        excluded: list[tuple[int, int]],
    ) -> list[NumericMention]:
        results: list[NumericMention] = []
        occupied = list(excluded)

        for match in _RANGE_PATTERN.finditer(clause.normalized_text):
            if self._overlaps(match.start(), match.end(), occupied):
                continue
            start = self._decimal(match.group("start"))
            end = self._decimal(match.group("end"))
            if start is None or end is None:
                continue
            unit = self._unit(match.group("unit"))
            low, high = sorted((start, end))
            results.append(
                NumericMention(
                    mention_id=self._id(
                        "number",
                        clause.clause_id,
                        match.start(),
                        match.end(),
                        f"{low}:{high}:{unit}",
                    ),
                    kind=NumericKind.RANGE,
                    amount=low,
                    range_end=high,
                    unit=unit,
                    operator=Operator.BETWEEN,
                    span=self._span(
                        clause,
                        block_raw_text,
                        normalization_map,
                        match.start(),
                        match.end(),
                    ),
                )
            )
            occupied.append((match.start(), match.end()))

        for match in _PERCENT_OF_PATTERN.finditer(clause.normalized_text):
            if self._overlaps(match.start(), match.end(), occupied):
                continue
            amount = self._decimal(match.group("number"))
            if amount is None:
                continue
            results.append(
                self._numeric_mention(
                    clause,
                    block_raw_text,
                    normalization_map,
                    match.start(),
                    match.end(),
                    amount,
                    unit="percent",
                    kind=NumericKind.PERCENTAGE,
                )
            )
            occupied.append((match.start(), match.end()))

        for match in _SINGLE_PATTERN.finditer(clause.normalized_text):
            if self._overlaps(match.start(), match.end(), occupied):
                continue
            amount = self._decimal(match.group("number"))
            if amount is None:
                continue
            currency = match.group("currency")
            unit = "cny" if currency else self._unit(match.group("unit"))
            kind = NumericKind.NUMBER
            if unit == "percent":
                kind = NumericKind.PERCENTAGE
            elif unit in {"cny", "cny_10k"}:
                kind = NumericKind.CURRENCY
            results.append(
                self._numeric_mention(
                    clause,
                    block_raw_text,
                    normalization_map,
                    match.start(),
                    match.end(),
                    amount,
                    unit=unit,
                    kind=kind,
                )
            )
            occupied.append((match.start(), match.end()))

        results.sort(key=lambda item: item.span.normalized_start)
        return results

    def _numeric_mention(
        self,
        clause: Clause,
        block_raw_text: str,
        normalization_map: NormalizationMap,
        start: int,
        end: int,
        amount: Decimal,
        *,
        unit: str | None,
        kind: NumericKind,
    ) -> NumericMention:
        return NumericMention(
            mention_id=self._id(
                "number",
                clause.clause_id,
                start,
                end,
                f"{amount}:{unit}:{kind.value}",
            ),
            kind=kind,
            amount=amount,
            unit=unit,
            operator=self._numeric_operator(clause.normalized_text, start),
            span=self._span(
                clause,
                block_raw_text,
                normalization_map,
                start,
                end,
            ),
        )

    def _units(
        self,
        clause: Clause,
        block_raw_text: str,
        normalization_map: NormalizationMap,
    ) -> list[UnitMention]:
        results: list[UnitMention] = []
        for match in _UNIT_PATTERN.finditer(clause.normalized_text):
            unit = self._unit(match.group())
            assert unit is not None
            results.append(
                UnitMention(
                    mention_id=self._id(
                        "unit",
                        clause.clause_id,
                        match.start(),
                        match.end(),
                        unit,
                    ),
                    unit=unit,
                    span=self._span(
                        clause,
                        block_raw_text,
                        normalization_map,
                        match.start(),
                        match.end(),
                    ),
                )
            )
        return results

    def _modalities(
        self,
        clause: Clause,
        block_raw_text: str,
        normalization_map: NormalizationMap,
    ) -> list[ModalityMention]:
        matches: list[tuple[int, int, Modality]] = []
        occupied: list[tuple[int, int]] = []
        for modality, pattern in _MODALITY_PATTERNS:
            for match in pattern.finditer(clause.normalized_text):
                if self._overlaps(match.start(), match.end(), occupied):
                    continue
                matches.append((match.start(), match.end(), modality))
                occupied.append((match.start(), match.end()))
        matches.sort()
        return [
            ModalityMention(
                mention_id=self._id(
                    "modality",
                    clause.clause_id,
                    start,
                    end,
                    modality.value,
                ),
                modality=modality,
                span=self._span(
                    clause,
                    block_raw_text,
                    normalization_map,
                    start,
                    end,
                ),
            )
            for start, end, modality in matches
        ]

    @staticmethod
    def _span(
        clause: Clause,
        block_raw_text: str,
        normalization_map: NormalizationMap,
        local_start: int,
        local_end: int,
    ) -> RuleSpan:
        normalized_start = clause.normalized_start + local_start
        normalized_end = clause.normalized_start + local_end
        raw_start, raw_end = normalization_map.raw_span(normalized_start, normalized_end)
        return RuleSpan(
            normalized_start=normalized_start,
            normalized_end=normalized_end,
            raw_start=raw_start,
            raw_end=raw_end,
            quote=block_raw_text[raw_start:raw_end],
        )

    @staticmethod
    def _id(
        kind: str,
        clause_id: str,
        start: int,
        end: int,
        value: str,
    ) -> str:
        raw = f"{kind}\x00{clause_id}\x00{start}\x00{end}\x00{value}"
        return f"sig_{sha256(raw.encode()).hexdigest()[:24]}"

    @staticmethod
    def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
        return any(
            existing_end > start and existing_start < end
            for existing_start, existing_end in occupied
        )

    @staticmethod
    def _unit(value: str | None) -> str | None:
        return None if value is None else _UNIT_ALIASES[value.lower()]

    @staticmethod
    def _decimal(value: str) -> Decimal | None:
        try:
            if re.fullmatch(_CHINESE_NUMBER, value):
                return Decimal(DeterministicRuleAnalyzer._chinese_integer(value))
            return Decimal(value.replace(",", ""))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _chinese_integer(value: str) -> int:
        digits = {
            "零": 0,
            "\u3007": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        small_units = {"十": 10, "百": 100, "千": 1_000}
        large_units = {"万": 10_000, "亿": 100_000_000}
        total = 0
        section = 0
        number = 0
        for char in value:
            if char in digits:
                number = digits[char]
            elif char in small_units:
                section += (number or 1) * small_units[char]
                number = 0
            elif char in large_units:
                total += (section + number or 1) * large_units[char]
                section = 0
                number = 0
            else:
                raise ValueError("unsupported Chinese numeral")
        return total + section + number

    @staticmethod
    def _numeric_operator(text: str, start: int) -> Operator | None:
        context = text[max(0, start - 16) : start]
        for operator, pattern in _OPERATOR_PATTERNS:
            if pattern.search(context):
                return operator
        return None

    @staticmethod
    def _date_operator(text: str, start: int) -> Operator | None:
        context = text[max(0, start - 16) : start]
        for operator, pattern in _DATE_OPERATOR_PATTERNS:
            if pattern.search(context):
                return operator
        return None
