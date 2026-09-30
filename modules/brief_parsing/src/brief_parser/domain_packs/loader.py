"""Safe loading and canonical compilation for declarative Domain Packs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from brief_parser.domain.domain_pack import DomainPack
from brief_parser.errors import BriefParserError, ErrorCode


class _NoAliasSafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader variant rejecting aliases because packs do not need them."""

    def compose_node(self, parent: object, index: object) -> object:
        if self.check_event(yaml.AliasEvent):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "YAML aliases are not allowed in Domain Packs",
                self.peek_event().start_mark,
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class DomainPackReferenceRegistry:
    """Allow only validator and compiler IDs implemented by trusted code."""

    def __init__(
        self,
        *,
        validator_ids: Iterable[str],
        compiler_ids: Iterable[str],
    ) -> None:
        self._validator_ids = frozenset(validator_ids)
        self._compiler_ids = frozenset(compiler_ids)

    def validate(self, pack: DomainPack) -> None:
        unknown_validators = set(pack.validators) - self._validator_ids
        unknown_compilers = set(pack.compilers) - self._compiler_ids
        if unknown_validators or unknown_compilers:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 引用了未注册的 Validator 或 Compiler。",
                details={
                    "unknown_validators": sorted(unknown_validators),
                    "unknown_compilers": sorted(unknown_compilers),
                },
            )


class DomainPackLoader:
    def __init__(
        self,
        registry: DomainPackReferenceRegistry,
        *,
        max_bytes: int = 256 * 1024,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._registry = registry
        self._max_bytes = max_bytes

    def load_yaml(self, path: Path) -> DomainPack:
        if path.suffix.lower() not in {".yaml", ".yml"}:
            self._invalid("Domain Pack 源文件必须使用 .yaml 或 .yml 后缀。")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "无法读取 Domain Pack。",
            ) from exc
        if len(content) > self._max_bytes:
            self._invalid("Domain Pack 超过允许大小。")
        try:
            text = content.decode("utf-8")
            payload = yaml.load(text, Loader=_NoAliasSafeLoader)
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 不是有效且安全的 UTF-8 YAML。",
            ) from exc
        return self._validate_payload(payload)

    def load_json(self, path: Path) -> DomainPack:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "无法读取编译后的 Domain Pack。",
            ) from exc
        if len(content) > self._max_bytes:
            self._invalid("Domain Pack 超过允许大小。")
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "编译后的 Domain Pack 不是有效 JSON。",
            ) from exc
        return self._validate_payload(payload)

    def canonical_json(self, pack: DomainPack) -> str:
        self._registry.validate(pack)
        return json.dumps(
            pack.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def load_directory(self, root: Path) -> dict[tuple[str, str], DomainPack]:
        catalog: dict[tuple[str, str], DomainPack] = {}
        for path in sorted((*root.rglob("*.yaml"), *root.rglob("*.yml"))):
            pack = self.load_yaml(path)
            key = (pack.id, pack.version)
            if key in catalog:
                self._invalid("Domain Pack id/version 不能重复。")
            catalog[key] = pack
        return catalog

    def _validate_payload(self, payload: Any) -> DomainPack:
        if not isinstance(payload, dict):
            self._invalid("Domain Pack 顶层必须是对象。")
        try:
            pack = DomainPack.model_validate(payload)
        except ValidationError as exc:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 无法通过 Schema 校验。",
                details={"validation_error_count": exc.error_count()},
            ) from exc
        self._registry.validate(pack)
        return pack

    @staticmethod
    def _invalid(message: str) -> None:
        raise BriefParserError(ErrorCode.DOMAIN_PACK_INVALID, message)
