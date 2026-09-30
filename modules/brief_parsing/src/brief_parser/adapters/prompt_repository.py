"""Filesystem adapter for immutable, versioned prompt templates."""

from __future__ import annotations

import re
from pathlib import Path

from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.prompt_repository import PromptTemplate


class FilePromptRepository:
    _SUPPORTED_ROLES = frozenset(
        {ModelRole.EXTRACTOR, ModelRole.AUDITOR, ModelRole.RESOLVER}
    )

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._cache: dict[tuple[ModelRole, str], PromptTemplate] = {}

    def get(self, *, role: ModelRole, version: str) -> PromptTemplate:
        if role not in self._SUPPORTED_ROLES or not re.fullmatch(
            rf"{re.escape(role.value)}/v[1-9]\d*",
            version,
        ):
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "Prompt role 或 version 不受支持。",
                details={"role": role.value, "version": version},
            )
        cache_key = (role, version)
        if cache_key in self._cache:
            return self._cache[cache_key]

        revision = version.rsplit("/", maxsplit=1)[1]
        path = (self._base_dir / role.value / f"{revision}.md").resolve()
        if self._base_dir not in path.parents:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "Prompt 路径无效。",
                details={"role": role.value, "version": version},
            )
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "配置的 Prompt 模板不可用。",
                details={"role": role.value, "version": version},
            ) from exc
        template = PromptTemplate(role=role, version=version, content=content)
        self._cache[cache_key] = template
        return template
