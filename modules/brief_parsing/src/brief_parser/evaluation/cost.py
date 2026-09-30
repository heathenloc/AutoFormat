"""Provider-neutral token cost estimation with explicit external pricing."""

from __future__ import annotations

from collections.abc import Iterable

from brief_parser.domain.pipeline import ProviderCallRecord
from brief_parser.evaluation.models import CostReport, PricingTable


def estimate_cost(
    calls: Iterable[ProviderCallRecord],
    pricing: PricingTable | None,
) -> CostReport:
    input_tokens = 0
    output_tokens = 0
    estimated_cost = 0.0
    priced_call_count = 0
    unpriced_call_count = 0
    unpriced_models: set[str] = set()
    for call in calls:
        input_tokens += call.input_tokens
        output_tokens += call.output_tokens
        price = None if pricing is None else pricing.models.get(call.model_id)
        if price is None:
            unpriced_call_count += 1
            unpriced_models.add(call.model_id)
            continue
        priced_call_count += 1
        estimated_cost += (
            call.input_tokens * price.input_usd_per_million_tokens
            + call.output_tokens * price.output_usd_per_million_tokens
        ) / 1_000_000
    return CostReport(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=round(estimated_cost, 8),
        priced_call_count=priced_call_count,
        unpriced_call_count=unpriced_call_count,
        unpriced_model_ids=sorted(unpriced_models),
        pricing_version=None if pricing is None else pricing.pricing_version,
    )
