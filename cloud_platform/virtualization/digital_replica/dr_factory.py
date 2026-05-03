"""
DR Factory Module
==================
Creates and updates Digital Replica (DR) documents using YAML-based schema templates
and Pydantic validation.

Architecture reasoning (from the lecture):
- The DRFactory is the *only* place where DR instances are born. By centralising
  creation here, we guarantee that every DR is structurally valid before it reaches
  the database.
- Each YAML template defines:
    • common_fields — fields shared by all DRs of this type (profile, metadata, …)
    • entity.data   — domain-specific data payload
    • validations   — mandatory fields, type constraints, enums, and init-defaults
- At creation time the factory:
    1. Dynamically builds Pydantic models from the YAML constraints.
    2. Validates supplied data against those models.
    3. Merges defaults from the 'initialization' section.
    4. Returns a plain dict ready for MongoDB insertion.
- Using Pydantic's `create_model` keeps the factory fully generic: adding a new DR
  type requires only a new YAML file — no Python code changes.
"""

from datetime import datetime
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, create_model, Field, field_validator
import yaml
import uuid


class DRFactory:
    """
    Factory for creating and updating Digital Replica documents.

    Instantiate with the path to a YAML schema template, then call
    create_dr() or update_dr() as needed.
    """

    def __init__(self, schema_path: str):
        self.schema = self._load_schema(schema_path)
        if not self.schema or "schemas" not in self.schema:
            raise ValueError(f"Invalid schema structure in {schema_path}")

    # ── Schema loading ────────────────────────────────────────────────

    def _load_schema(self, path: str) -> Dict:
        """Load and parse the YAML template file."""
        try:
            with open(path, "r") as file:
                return yaml.safe_load(file)
        except Exception as e:
            raise ValueError(f"Failed to load schema: {str(e)}")

    # ── Dynamic Pydantic model creation ───────────────────────────────
    # The lecture builds Pydantic models on the fly so that validation rules
    # are defined once (in YAML) and enforced everywhere.

    def _create_profile_model(self) -> Type[BaseModel]:
        """
        Build a Pydantic model for the 'profile' section of the DR.

        Mandatory fields (from validations.mandatory_fields.profile) are marked
        as required (...); optional fields default to None.
        Numeric constraints (min/max) and enum constraints are applied as Field
        kwargs or field validators.
        """
        mandatory_fields = (
            self.schema["schemas"]
            .get("validations", {})
            .get("mandatory_fields", {})
            .get("profile", [])
        )
        type_constraints = (
            self.schema["schemas"].get("validations", {}).get("type_constraints", {})
        )

        field_definitions = {}
        profile_fields = self.schema["schemas"]["common_fields"].get("profile", {})

        for field_name, field_type in profile_fields.items():
            is_required = field_name in mandatory_fields
            constraints = {}

            # Apply numeric range constraints if defined
            if field_name in type_constraints:
                rules = type_constraints[field_name]
                if "min" in rules:
                    constraints["ge"] = rules["min"]
                if "max" in rules:
                    constraints["le"] = rules["max"]

            # Map YAML type strings to Python types
            python_type = self._yaml_type_to_python(field_type)

            field_definitions[field_name] = (
                python_type,
                Field(... if is_required else None, **constraints),
            )

        model = create_model("Profile", **field_definitions)

        # Attach enum validators where needed
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

    def _create_data_model(self) -> Type[BaseModel]:
        """
        Build a Pydantic model for the 'entity.data' section of the DR.

        Handles primitive types, List[Dict] (measurements), and List[str] (device IDs, etc.).
        Measurement list items can have their own sub-constraints (required_fields,
        type_mappings) which are enforced via a field_validator.
        """
        type_constraints = (
            self.schema["schemas"].get("validations", {}).get("type_constraints", {})
        )
        data_fields = self.schema["schemas"].get("entity", {}).get("data", {})

        field_definitions = {}
        for field_name, field_type in data_fields.items():
            if field_type == "List[Dict]":
                field_definitions[field_name] = (
                    List[Dict[str, Any]],
                    Field(default_factory=list),
                )
            elif field_type == "List[str]":
                field_definitions[field_name] = (List[str], Field(default_factory=list))
            else:
                python_type = self._yaml_type_to_python(field_type)
                # Wrap in Optional so Pydantic v2 accepts None as default
                field_definitions[field_name] = (Optional[python_type], Field(None))

        model = create_model("Data", **field_definitions)

        # Add validators for List[Dict] fields with item_constraints
        for field_name, field_type in data_fields.items():
            if field_name in type_constraints and "enum" in type_constraints[field_name]:
                enum_values = type_constraints[field_name]["enum"]

                @field_validator(field_name)
                def validate_enum(value, field):
                    if value not in enum_values:
                        raise ValueError(f"{field.name} must be one of {enum_values}")
                    return value

                setattr(model, f"validate_{field_name}", validate_enum)

            if field_type == "List[Dict]" and field_name in type_constraints:
                rules = type_constraints[field_name]
                if "item_constraints" in rules:
                    item_rules = rules["item_constraints"]
                    required_fields = item_rules.get("required_fields", [])
                    type_mappings = item_rules.get("type_mappings", {})

                    @field_validator(field_name)
                    def validate_list_items(value, field):
                        if not isinstance(value, list):
                            raise ValueError(f"{field.name} must be a list")
                        for idx, item in enumerate(value):
                            if not isinstance(item, dict):
                                raise ValueError(f"Item {idx} in {field.name} must be a dict")
                            missing = [f for f in required_fields if f not in item]
                            if missing:
                                raise ValueError(f"Missing required fields {missing} in item {idx}")
                            for key, expected_type in type_mappings.items():
                                if key in item:
                                    val = item[key]
                                    if expected_type == "datetime":
                                        if not isinstance(val, (datetime, str)):
                                            raise ValueError(f"Field {key} in item {idx} must be a datetime")
                                    elif expected_type == "float":
                                        try:
                                            item[key] = float(val)
                                        except (TypeError, ValueError):
                                            raise ValueError(f"Field {key} in item {idx} must be a number")
                        return value

                    setattr(model, f"validate_{field_name}", validate_list_items)

        return model

    # ── DR creation ───────────────────────────────────────────────────

    def create_dr(self, dr_type: str, initial_data: Dict[str, Any]) -> Dict:
        """
        Create a new Digital Replica document.

        Steps:
            1. Build Pydantic models for profile and data sections.
            2. Initialise the DR dict with a UUID _id and timestamps.
            3. Apply default values from the 'initialization' section.
            4. Merge and validate the caller-supplied data.
            5. Return the complete DR dict (ready for database insertion).

        Args:
            dr_type:      Type label (e.g. 'gateway', 'sensor').
            initial_data: Caller-supplied fields (profile, data, metadata).

        Returns:
            A complete DR document dict.
        """
        # Dynamically build Pydantic models from the YAML schema
        ProfileModel = self._create_profile_model()
        DataModel = self._create_data_model()

        # Scaffold the DR with required fields and timestamps
        dr_dict = {
            "_id": str(uuid.uuid4()),
            "type": dr_type,
            "metadata": {
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
            "data": {},
        }

        # Apply initialisation defaults from the YAML template
        init_values = (
            self.schema["schemas"].get("validations", {}).get("initialization", {})
        )
        for section, defaults in init_values.items():
            if section == "metadata":
                dr_dict["metadata"].update(defaults)
            elif section == "profile":
                # Profile defaults are merged into a 'profile' sub-dict
                dr_dict.setdefault("profile", {}).update(defaults)
            elif section in ["status", "sensors", "devices", "measurements"]:
                # These operational fields live inside 'data'
                dr_dict["data"][section] = defaults
            else:
                dr_dict[section] = defaults

        # Validate and merge caller-supplied profile data
        if "profile" in initial_data:
            profile = ProfileModel(**initial_data["profile"])
            dr_dict["profile"] = profile.model_dump(exclude_unset=True)

        # Validate and merge caller-supplied entity data
        if "data" in initial_data:
            data = DataModel(**{**dr_dict["data"], **initial_data["data"]})
            dr_dict["data"] = data.model_dump(exclude_unset=True)

        # Merge any extra metadata supplied by the caller
        if "metadata" in initial_data:
            dr_dict["metadata"].update(initial_data["metadata"])

        return dr_dict

    # ── DR update ─────────────────────────────────────────────────────

    def update_dr(self, dr: Dict[str, Any], updates: Dict[str, Any]) -> Dict:
        """
        Apply partial updates to an existing DR, re-validating each section.

        Args:
            dr:      The current DR dict.
            updates: A dict of fields to change (profile, data, metadata).

        Returns:
            The updated DR dict.
        """
        ProfileModel = self._create_profile_model()
        DataModel = self._create_data_model()

        updated_dr = dr.copy()

        if "profile" in updates:
            current_profile = updated_dr.get("profile", {})
            profile = ProfileModel(**(current_profile | updates["profile"]))
            updated_dr["profile"] = profile.model_dump(exclude_unset=True)

        if "data" in updates:
            current_data = updated_dr.get("data", {})
            data = DataModel(**(current_data | updates["data"]))
            updated_dr["data"] = data.model_dump(exclude_unset=True)

        if "metadata" in updates:
            updated_dr["metadata"].update(updates["metadata"])

        # Always bump the timestamp on update
        updated_dr["metadata"]["updated_at"] = datetime.utcnow()

        return updated_dr

    # ── Utility ───────────────────────────────────────────────────────

    @staticmethod
    def _yaml_type_to_python(yaml_type: str):
        """Map a YAML type string to the corresponding Python type."""
        mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "datetime": datetime,
        }
        return mapping.get(yaml_type, Any)
