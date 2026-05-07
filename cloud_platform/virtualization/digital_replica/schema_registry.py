"""
Schema Registry Module (DR wrapper)
===================================
Backward-compatible wrapper that exposes the DR schema registry.
"""

from .dr_schema_registry import DRSchemaRegistry
from .history_schema_registry import HistorySchemaRegistry


class SchemaRegistry(DRSchemaRegistry):
    """Backwards-compatible alias for the DR schema registry."""


__all__ = ["SchemaRegistry", "DRSchemaRegistry", "HistorySchemaRegistry"]
