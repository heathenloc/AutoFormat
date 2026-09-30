"""Declarative Domain Pack v1 contract."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, Locale, SemanticVersion, StrictModel
from brief_parser.domain.enums import Modality, Priority


class DomainCategory(StrictModel):
    id: Identifier
    aliases: list[str] = Field(default_factory=list)
    risk: Priority = Priority.NORMAL


class DomainPack(StrictModel):
    schema_version: Literal["domain-pack/1.0"] = "domain-pack/1.0"
    id: Identifier
    version: SemanticVersion
    locales: Annotated[list[Locale], Field(min_length=1)]
    categories: list[DomainCategory] = Field(default_factory=list)
    modality_lexicon: dict[Modality, list[str]] = Field(default_factory=dict)
    validators: list[Identifier] = Field(default_factory=list)
    compilers: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        category_ids = [category.id for category in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("category ids must be unique")
        if len(self.validators) != len(set(self.validators)):
            raise ValueError("validator ids must be unique")
        if len(self.compilers) != len(set(self.compilers)):
            raise ValueError("compiler ids must be unique")
        if len(self.locales) != len(set(self.locales)):
            raise ValueError("locales must be unique")

        category_terms: dict[str, str] = {}
        for category in self.categories:
            for term in (category.id, *category.aliases):
                normalized = term.casefold().strip()
                owner = category_terms.get(normalized)
                if owner is not None and owner != category.id:
                    raise ValueError("category ids and aliases must be unambiguous")
                category_terms[normalized] = category.id

        modality_terms: dict[str, Modality] = {}
        for modality, terms in self.modality_lexicon.items():
            for term in terms:
                normalized = term.casefold().strip()
                if not normalized:
                    raise ValueError("modality lexicon terms must be non-empty")
                owner = modality_terms.get(normalized)
                if owner is not None and owner != modality:
                    raise ValueError("modality lexicon terms must be unambiguous")
                modality_terms[normalized] = modality
        return self
