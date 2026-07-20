"""Deterministic prompt compiler with an explicit product identity anchor."""

from __future__ import annotations

from .models import GenerationItem, GenerationRequest


def compile_prompt(request: GenerationRequest, item: GenerationItem) -> str:
    instruction = " ".join(item.prompt.split())
    approved_assets = ",".join(sorted(item.input_asset_ids))
    lines = [
        f"role={item.role}",
        f"product_id={request.product_id}",
    ]
    if request.sku_id is not None:
        lines.append(f"sku_id={request.sku_id}")
    lines.extend(
        [
            f"size={item.width}x{item.height}",
            f"approved_asset_ids={approved_assets}",
            f"instruction={instruction}",
        ]
    )
    return "\n".join(lines)
