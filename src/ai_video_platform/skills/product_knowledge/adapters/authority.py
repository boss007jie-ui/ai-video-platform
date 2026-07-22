"""Unforgeable-by-public-interface capability for the sole Library writer."""

from __future__ import annotations

from ..errors import ProductKnowledgeError, ProductKnowledgeErrorCode


_PRODUCT_KNOWLEDGE_WRITER = object()


def require_product_knowledge_writer(authority: object) -> None:
    if authority is not _PRODUCT_KNOWLEDGE_WRITER:
        raise ProductKnowledgeError(
            ProductKnowledgeErrorCode.PRODUCT_LIBRARY_WRITE_FORBIDDEN,
            "Only Product Knowledge may write Product Library",
        )
