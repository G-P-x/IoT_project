"""
History Factory Module
======================
Creates historical event records using YAML-based templates.
"""

from datetime import datetime
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, create_model, Field, field_validator
import yaml
import uuid


class HistoryFactory:
    """
    Factory for creating history/event documents from YAML templates.
    """

    def __init__(self, schema_path: str):
        self.schema = self._load_schema(schema_path)
        if not self.schema or "schemas" not in self.schema:
            raise ValueError(f"Invalid schema structure in {schema_path}")

    def _load_schema(self, path: str) -> Dict:
        try:
            with open(path, "r") as file:
                return yaml.safe_load(file)
        except Exception as e:
            raise ValueError(f"Failed to load schema: {str(e)}")

    def _create_data_model(self) -> Type[BaseModel]:
        """Build a Pydantic model for the 'entity.data' section."""
        type_constraints = (
            self.schema["schemas"].get("validations", {}).get("type_constraints", {})
        )
        data_fields = self.schema["schemas"].get("entity", {}).get("data", {})
        mandatory_fields = (
            self.schema["schemas"].get("validations", {}).get("mandatory_fields", {})
        )
        mandatory_data_fields = []
        if isinstance(mandatory_fields, dict):
            mandatory_data_fields = list(mandatory_fields.get("entity.data", []) or [])
            if not mandatory_data_fields:
                mandatory_data_fields = list(mandatory_fields.get("data", []) or [])

        field_definitions = {}
        for field_name, field_type in data_fields.items():
            is_required = field_name in mandatory_data_fields
            if field_type == "List[Dict]":
                field_definitions[field_name] = (
                    List[Dict[str, Any]],
                    Field(... if is_required else None, default_factory=None if is_required else list),
                )
            elif field_type == "List[str]":
                field_definitions[field_name] = (
                    List[str],
                    Field(... if is_required else None, default_factory=None if is_required else list),
                )
            else:
                python_type = self._yaml_type_to_python(field_type)
                if is_required:
                    field_definitions[field_name] = (python_type, Field(...))
                else:
                    field_definitions[field_name] = (Optional[python_type], Field(None))

        model = create_model("HistoryData", **field_definitions)

        for field_name in field_definitions:
            if field_name in type_constraints and "enum" in type_constraints[field_name]:
                enum_values = type_constraints[field_name]["enum"]

                @field_validator(field_name)
                def validate_enum(value, field):
                    if value not in enum_values:
                        raise ValueError(f"{field.name} must be one of {enum_values}")
                    return value

                setattr(model, f"validate_{field_name}", validate_enum)

        return model

    def create_record(self, initial_data: Dict[str, Any]) -> Dict:
        """
        Create a new history record.

        Args:
            initial_data: Caller-supplied fields (root, data, metadata).

        Returns:
            A complete history record dict.
        """
        DataModel = self._create_data_model()

        record = {
            "_id": str(uuid.uuid4()),
            "data": {},
        }

        data_payload = dict(initial_data.get("data", {}))
        if "timestamp" in data_payload:
            if "timestamp" not in initial_data:
                record["timestamp"] = data_payload["timestamp"]
            data_payload.pop("timestamp", None)

        init_values = (
            self.schema["schemas"].get("validations", {}).get("initialization", {})
        )
        data_fields = self.schema["schemas"].get("entity", {}).get("data", {})

        for section, defaults in init_values.items():
            if section == "root":
                record.update(defaults)
            elif section == "metadata":
                record.setdefault("metadata", {}).update(defaults)
            elif section in ["entity.data", "data"]:
                record["data"].update(defaults)
            elif section in data_fields:
                record["data"][section] = defaults
            else:
                record[section] = defaults

        for key, value in initial_data.items():
            if key in ["data", "metadata"]:
                continue
            record[key] = value

        if "metadata" in initial_data:
            record.setdefault("metadata", {}).update(initial_data["metadata"])

        if "data" in initial_data:
            data = DataModel(**{**record["data"], **data_payload})
            record["data"] = data.model_dump(exclude_unset=True)
        elif record["data"]:
            data = DataModel(**record["data"])
            record["data"] = data.model_dump(exclude_unset=True)

        self._validate_required_root(record)

        return record

    def _validate_required_root(self, record: Dict[str, Any]) -> None:
        mandatory_fields = (
            self.schema["schemas"].get("validations", {}).get("mandatory_fields", {})
        )
        required_root: List[str] = []
        if isinstance(mandatory_fields, dict):
            required_root = list(mandatory_fields.get("root", []) or [])
        elif isinstance(mandatory_fields, list):
            required_root = list(mandatory_fields)

        missing = [f for f in required_root if f not in record or record[f] is None]
        if missing:
            raise ValueError(f"Missing required root fields: {missing}")

    @staticmethod
    def _yaml_type_to_python(yaml_type: str):
        mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "datetime": datetime,
        }
        return mapping.get(yaml_type, Any)
