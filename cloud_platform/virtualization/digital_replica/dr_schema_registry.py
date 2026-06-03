"""
DR Schema Registry Module
=========================
Loads Digital Replica (DR) YAML templates and converts them into MongoDB
$jsonSchema validation documents.
"""

from typing import Dict, List, Tuple
import yaml


class DRSchemaRegistry:
    """
    Loads YAML-based DR templates and converts them to MongoDB validation schemas.

    DRs use `dr_type` as their discriminator field.
    """

    def __init__(self):
        # Maps DR type name -> MongoDB $jsonSchema validation dict
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

            validation_schema = self._convert_yaml_to_mongodb_schema(
                raw_schema["schemas"],
                discriminator_key="dr_type",
            )
            self.schemas[schema_type] = validation_schema

        except Exception as e:
            raise ValueError(f"Failed to load schema from {yaml_path}: {str(e)}")

    def _convert_yaml_to_mongodb_schema(self, yaml_schema: Dict, discriminator_key: str) -> Dict:
        """
        Translate the YAML schema definition into a MongoDB $jsonSchema document.
        """

        def convert_type(yaml_type: str) -> str:
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
            if isinstance(field_def, str):
                return {"bsonType": convert_type(field_def)}
            if isinstance(field_def, dict):
                return {
                    "bsonType": "object",
                    "properties": {k: process_field(v) for k, v in field_def.items()},
                }
            if isinstance(field_def, list):
                return {"bsonType": "array"}
            return field_def

        properties: Dict[str, Dict] = {}

        if "common_fields" in yaml_schema:
            for field_name, field_def in yaml_schema["common_fields"].items():
                properties[field_name] = process_field(field_def)

        if "entity" in yaml_schema and "data" in yaml_schema["entity"]:
            properties["data"] = process_field(yaml_schema["entity"]["data"])

        root_req, profile_req, metadata_req, data_req = self._collect_required_fields(
            yaml_schema.get("validations", {}).get("mandatory_fields")
        )

        if discriminator_key not in properties:
            properties[discriminator_key] = {"bsonType": "string"}

        if profile_req:
            profile_schema = properties.get("profile") or {"bsonType": "object", "properties": {}}
            profile_schema["required"] = self._unique(profile_req)
            properties["profile"] = profile_schema

        if metadata_req:
            metadata_schema = properties.get("metadata") or {"bsonType": "object", "properties": {}}
            metadata_schema["required"] = self._unique(metadata_req)
            properties["metadata"] = metadata_schema

        if data_req:
            data_schema = properties.get("data") or {"bsonType": "object", "properties": {}}
            data_schema["required"] = self._unique(data_req)
            properties["data"] = data_schema

        root_required = self._unique(["_id", discriminator_key] + root_req)

        validation_schema = {
            "$jsonSchema": {
                "bsonType": "object",
                "required": root_required,
                "properties": {
                    "_id": {"bsonType": "string"},
                    **properties,
                },
            }
        }

        return validation_schema

    def _collect_required_fields(
        self, mandatory_fields
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        root_req: List[str] = []
        profile_req: List[str] = []
        metadata_req: List[str] = []
        data_req: List[str] = []

        if isinstance(mandatory_fields, dict):
            root_req = list(mandatory_fields.get("root", []) or [])
            profile_req = list(mandatory_fields.get("profile", []) or [])
            metadata_req = list(mandatory_fields.get("metadata", []) or [])
            data_req = list(mandatory_fields.get("entity.data", []) or [])
            if not data_req:
                data_req = list(mandatory_fields.get("data", []) or [])
        elif isinstance(mandatory_fields, list):
            root_req = list(mandatory_fields)

        return root_req, profile_req, metadata_req, data_req

    def _unique(self, items: List[str]) -> List[str]:
        seen = set()
        result = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def get_collection_name(self, schema_type: str) -> str:
        schemes = ["gateway", "sensor", "actuator", "device"]
        if schema_type in schemes:
            return "device_collection"
        else:
            return "history_collection"


    def get_validation_schema(self, schema_type: str) -> Dict:
        if schema_type not in self.schemas:
            raise ValueError(f"Schema not found for type: {schema_type}")
        return self.schemas[schema_type]