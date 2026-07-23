"""Immutable product data used by the image and panel generation seam."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class ProductFacts:
    """Product-only facts with no execution or transport concerns."""

    product_id: str
    sku_id: str | None = None
    facts: tuple[Mapping[str, Any], ...] = ()
    approved_asset_ids: tuple[str, ...] = ()
    visual_constraints: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    packaging: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    dimensions: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    category_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", tuple(_freeze(fact) for fact in self.facts))
        object.__setattr__(self, "approved_asset_ids", tuple(str(item) for item in self.approved_asset_ids))
        object.__setattr__(self, "category_ids", tuple(str(item) for item in self.category_ids))
        for name in ("visual_constraints", "packaging", "dimensions"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    def repair_story_context(self, submitted_context: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Fill a partial story context from this product's confirmed data."""

        context = dict(_mapping(submitted_context))
        context.setdefault("product_id", self.product_id)
        if self.sku_id is not None:
            context.setdefault("sku_id", self.sku_id)
        if not context.get("facts"):
            context["facts"] = self.facts
        if not context.get("visual_constraints") and self.visual_constraints:
            context["visual_constraints"] = self.visual_constraints
        return _freeze(context)


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    """Channel expression parameters kept separate from product facts."""

    channel_id: str
    format: str = "product-showcase"
    objective: str | None = None
    audience: str | None = None
    locale: str | None = None

    def derive_product_mode(self, product: ProductFacts) -> str:
        """Choose a deterministic presentation mode from channel and product data."""

        explicit = product.visual_constraints.get("product_mode")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        if self.objective in {"conversion", "direct-response", "direct_response"}:
            return "direct-response"
        if self.format in {"catalog", "catalogue", "listing"}:
            return "catalog"
        return "product-showcase"


def _payload(source: object) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    candidate = getattr(source, "payload", None)
    if isinstance(candidate, Mapping):
        return candidate
    raise TypeError("product source must be a mapping or expose a mapping payload")


def to_product_facts(source: object) -> ProductFacts:
    """Map a contract-like product payload into pure product data."""

    payload = _payload(source)
    product_id = payload.get("product_id")
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("product_id is required")
    raw_facts = payload.get("facts", ())
    if not isinstance(raw_facts, (list, tuple)):
        raise TypeError("facts must be a sequence")
    facts = tuple(fact for fact in raw_facts if isinstance(fact, Mapping))
    approved = payload.get("approved_asset_refs", payload.get("approved_asset_ids", ()))
    if not isinstance(approved, (list, tuple)):
        raise TypeError("approved_asset_refs must be a sequence")
    return ProductFacts(
        product_id=product_id,
        sku_id=payload.get("sku_id") if isinstance(payload.get("sku_id"), str) else None,
        facts=facts,
        approved_asset_ids=tuple(item for item in approved if isinstance(item, str)),
        visual_constraints=_mapping(payload.get("visual_constraints")),
        packaging=_mapping(payload.get("packaging")),
        dimensions=_mapping(payload.get("dimensions")),
        category_ids=tuple(
            item
            for item in payload.get("category_ids", ())
            if isinstance(item, str)
        ),
    )


def repair_story_context(
    product: ProductFacts,
    submitted_context: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    return product.repair_story_context(submitted_context)


def derive_product_mode(product: ProductFacts, channel: ChannelProfile) -> str:
    return channel.derive_product_mode(product)


__all__ = [
    "ChannelProfile",
    "ProductFacts",
    "derive_product_mode",
    "repair_story_context",
    "to_product_facts",
]
