"""
Schema Registry Module
=======================
Central registry that loads YAML schema templates and converts them into MongoDB
$jsonSchema validation documents.

Architecture reasoning (from the lecture):
- The SchemaRegistry is the single source of truth for DR structure definitions.
- It decouples the schema *format* (human-authored YAML files) from the schema
  *consumer* (MongoDB validation, DRFactory, DatabaseService).
- When a new DR type is needed (e.g. a new kind of sensor), you only add a YAML
  file and call `load_schema()` — no code changes are required in the DB or DT
  layers.
- The `get_collection_name()` method enforces a naming convention
  (`<type>_collection`) so that every layer agrees on where documents live.
"""

from typing import Dict
import yaml


class SchemaRegistry:
    """
    Loads YAML-based DR templates and converts them to MongoDB validation schemas.

    Usage:
        registry = SchemaRegistry()
        registry.load_schema('gateway', 'cloud_platform/virtualization/templates/gateway.yaml')
        registry.load_schema('sensor',  'cloud_platform/virtualization/templates/sensor.yaml')
    """

    def __init__(self):
        # Maps DR type name → MongoDB $jsonSchema validation dict
        self.schemas: Dict[str, Dict] = {}

    def load_schema(self, schema_type: str, yaml_path: str) -> None:
        """
        Parse a YAML template and store the resulting MongoDB validation schema.

        Args:
            schema_type: Logical name for this DR type (e.g. 'gateway').
            yaml_path:   Path to the YAML template file.

        Raises:
            ValueError: If the YAML is missing the required 'schemas' key.
        """
        try:
            with open(yaml_path, "r") as file:
                raw_schema = yaml.safe_load(file)

            if not raw_schema or "schemas" not in raw_schema:
                raise ValueError(f"Invalid schema structure in {yaml_path}")

            # Convert the human-readable YAML into MongoDB's $jsonSchema format
            validation_schema = self._convert_yaml_to_mongodb_schema(raw_schema["schemas"])
            self.schemas[schema_type] = validation_schema

        except Exception as e:
            raise ValueError(f"Failed to load schema from {yaml_path}: {str(e)}")

    # ── Internal helpers ──────────────────────────────────────────────

    def _convert_yaml_to_mongodb_schema(self, yaml_schema: Dict) -> Dict:
        """
        Translate the YAML schema definition into a MongoDB $jsonSchema document.

        The mapping covers:
            - common_fields → top-level properties (profile, metadata, …)
            - entity.data   → the 'data' sub-document
            - validations   → required fields list

        Mongo BSON types are derived from the YAML type strings via a simple lookup.
        """

        def convert_type(yaml_type: str) -> str:
            """Map a YAML type hint to a MongoDB BSON type string."""
            type_mapping = {
                "str": "string",
                "int": "int",
                "float": "double",
                "bool": "bool",
                "datetime": "date",
                "Dict": "object",
                "List": "array",
            }
            return type_mapping.get(yaml_type, yaml_type)

        def process_field(field_def):
            """
            Recursively convert a single field definition.

            - str  → {"bsonType": "string"}
            - dict → {"bsonType": "object", "properties": {…}}
            - list → {"bsonType": "array"}
            """
            if isinstance(field_def, str):
                return {"bsonType": convert_type(field_def)}
            elif isinstance(field_def, dict):
                return {
                    "bsonType": "object",
                    "properties": {k: process_field(v) for k, v in field_def.items()},
                }
            elif isinstance(field_def, list):
                return {"bsonType": "array"}
            return field_def

        # Process common_fields (profile, metadata, …)
        properties = {}
        if "common_fields" in yaml_schema:
            for field_name, field_def in yaml_schema["common_fields"].items():
                properties[field_name] = process_field(field_def)

        # Process entity-specific data fields
        if "entity" in yaml_schema and "data" in yaml_schema["entity"]:
            properties["data"] = process_field(yaml_schema["entity"]["data"])

        # Collect required fields from validations section
        required_fields = []
        if "validations" in yaml_schema:
            if "required" in yaml_schema["validations"]:
                required_fields.extend(yaml_schema["validations"]["required"])

        # Build the final MongoDB validation schema
        validation_schema = {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "type"] + required_fields,
                "properties": {
                    "_id": {"bsonType": "string"},
                    "type": {"bsonType": "string"},
                    **properties,
                },
            }
        }

        return validation_schema

    # ── Public accessors ──────────────────────────────────────────────

    def get_collection_name(self, schema_type: str) -> str:
        """
        Derive the MongoDB collection name for a given DR type.

        Convention: '<type>_collection'  (e.g. 'gateway_collection').
        """
        return f"{schema_type}_collection"

    def get_validation_schema(self, schema_type: str) -> Dict:
        """
        Return the MongoDB $jsonSchema for the given DR type.

        Raises:
            ValueError: If no schema has been loaded for this type.
        """
        if schema_type not in self.schemas:
            raise ValueError(f"Schema not found for type: {schema_type}")
        return self.schemas[schema_type]
