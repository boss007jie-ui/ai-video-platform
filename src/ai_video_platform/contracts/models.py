"""Typed foundation payload projections mechanically derived from registry."""

from __future__ import annotations

from dataclasses import field, make_dataclass
from types import MappingProxyType
from typing import Any

from .registry import REGISTRY
from .serialization import freeze_json, thaw_json


class FoundationPayloadModel:
    __slots__ = ("_contract_payload",)

    def __contract_json__(self) -> object:
        return thaw_json(self._contract_payload)


def _create_model(
    name: str,
    required_fields: tuple[str, ...],
    optional_fields: tuple[str, ...],
) -> type:
    def _freeze_fields(self: object) -> None:
        for field_name in (*required_fields, *optional_fields):
            object.__setattr__(self, field_name, freeze_json(getattr(self, field_name)))

    return make_dataclass(
        name,
        [
            *[(field_name, Any) for field_name in required_fields],
            *[(field_name, Any | None, field(default=None)) for field_name in optional_fields],
        ],
        frozen=True,
        slots=True,
        bases=(FoundationPayloadModel,),
        module=__name__,
        namespace={"__post_init__": _freeze_fields},
    )


_MODELS = {
    contract_type: _create_model(
        definition.name,
        definition.required_fields,
        definition.optional_fields,
    )
    for contract_type, definition in REGISTRY.items()
}
globals().update({model.__name__: model for model in _MODELS.values()})
MODEL_REGISTRY = MappingProxyType(_MODELS)

__all__ = ["MODEL_REGISTRY", *[model.__name__ for model in _MODELS.values()]]
