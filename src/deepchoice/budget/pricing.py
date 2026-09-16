"""Explicitly versioned price catalog contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PriceStatus(StrEnum):
    PRICED = "priced"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ModelTokenPrice(_FrozenContract):
    schema_version: Literal[1] = 1
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_micro_usd_per_million_tokens: int = Field(ge=0)
    output_micro_usd_per_million_tokens: int = Field(ge=0)


class PriceQuote(_FrozenContract):
    schema_version: Literal[1] = 1
    catalog_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    status: PriceStatus
    input_micro_usd_per_million_tokens: int | None = Field(default=None, ge=0)
    output_micro_usd_per_million_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _prices_match_status(self) -> "PriceQuote":
        price_count = sum(
            price is not None
            for price in (
                self.input_micro_usd_per_million_tokens,
                self.output_micro_usd_per_million_tokens,
            )
        )
        if self.status is PriceStatus.PRICED and price_count != 2:
            raise ValueError("priced quotes require both token prices")
        if self.status is not PriceStatus.PRICED and price_count != 0:
            raise ValueError("unpriced quotes cannot carry token prices")
        return self


class PriceCatalog(_FrozenContract):
    schema_version: Literal[1] = 1
    catalog_version: str = Field(min_length=1)
    prices: tuple[ModelTokenPrice, ...] = ()

    @model_validator(mode="after")
    def _unique_models(self) -> "PriceCatalog":
        identities = [(price.provider, price.model) for price in self.prices]
        if len(identities) != len(set(identities)):
            raise ValueError("catalog provider/model entries must be unique")
        return self

    def quote(self, *, provider: str, model: str) -> PriceQuote:
        if not provider or not model:
            raise ValueError("provider and model must be non-empty")
        for price in self.prices:
            if price.provider == provider and price.model == model:
                return PriceQuote(
                    catalog_version=self.catalog_version,
                    provider=provider,
                    model=model,
                    status=PriceStatus.PRICED,
                    input_micro_usd_per_million_tokens=(
                        price.input_micro_usd_per_million_tokens
                    ),
                    output_micro_usd_per_million_tokens=(
                        price.output_micro_usd_per_million_tokens
                    ),
                )
        return PriceQuote(
            catalog_version=self.catalog_version,
            provider=provider,
            model=model,
            status=PriceStatus.UNKNOWN,
        )


CURRENT_PRICE_CATALOG = PriceCatalog(catalog_version="unpriced-v1")


__all__ = [
    "CURRENT_PRICE_CATALOG",
    "ModelTokenPrice",
    "PriceCatalog",
    "PriceQuote",
    "PriceStatus",
]
