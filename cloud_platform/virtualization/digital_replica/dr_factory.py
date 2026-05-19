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
from typing import Dict, Any, Optional, Type, List, get_args, get_origin, Union
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

    # ── Schema helpers ───────────────────────────────────────────────

    @staticmethod
    def _as_optional_type(python_type):
        # Normalize to Optional[T] without nesting Optional[Optional[T]].
        origin = get_origin(python_type)
        if origin is Union and type(None) in get_args(python_type):
            return python_type
        return Optional[python_type]

    @staticmethod
    def _is_nullable(rules: Dict[str, Any]) -> bool:
        return rules.get("nullable") is True or rules.get("type") == "nullable"

    @staticmethod
    def _build_enum_validator(field_name: str, enum_values: List[Any]):
        @field_validator(field_name)
        def _validate_enum(cls, value, enum_values=tuple(enum_values), field_name=field_name):
            # Allow None; nullability is handled by schema rules.
            if value is None:
                return value
            if value not in enum_values:
                raise ValueError(f"{field_name} must be one of {list(enum_values)}")
            return value

        return _validate_enum

    @staticmethod
    def _build_list_items_validator(
        field_name: str, required_fields: List[str], type_mappings: Dict[str, str]
    ):

        @field_validator(field_name) # This pydantic decorator registers the function below (_validate_list_items) as a validator for the specified field_name.
        # This way, every time the field is set/parsed, the _validate_list_items function will be called to check the contents of the list against the defined rules.
        def _validate_list_items(
            cls,
            value,
            field_name=field_name,
            required_fields=tuple(required_fields),
            type_mappings=type_mappings,
        ):
            # Validate list items against per-item schema rules from YAML.
            if value is None:
                return value
            if not isinstance(value, list):
                raise ValueError(f"{field_name} must be a list")
            for idx, item in enumerate(value):
                if not isinstance(item, dict):
                    raise ValueError(f"Item {idx} in {field_name} must be a dict")
                missing = [f for f in required_fields if f not in item]
                if missing:
                    raise ValueError(f"Missing required fields {missing} in item {idx}")
                for key, expected_type in type_mappings.items():
                    if key in item:
                        val = item[key]
                        if expected_type == "datetime":
                            if not isinstance(val, (datetime, str)):
                                raise ValueError(
                                    f"Field {key} in item {idx} must be a datetime"
                                )
                        elif expected_type == "float":
                            try:
                                item[key] = float(val)
                            except (TypeError, ValueError):
                                raise ValueError(
                                    f"Field {key} in item {idx} must be a number"
                                )
            return value

        return _validate_list_items

    def _create_section_model(
        self, name: str, fields: Dict[str, Any], mandatory_fields: List[str]
    ) -> Optional[Type[BaseModel]]:
        if not fields:
            return None

        type_constraints = (
            self.schema["schemas"].get("validations", {}).get("type_constraints", {})
        )
        # Assemble field definitions and validators for create_model.
        field_definitions = {}
        validators = {}

        for field_name, field_type in fields.items():
            is_required = field_name in mandatory_fields
            rules = type_constraints.get(field_name, {})
            constraints = {}

            if "min" in rules:
                constraints["ge"] = rules["min"]
            if "max" in rules:
                constraints["le"] = rules["max"]

            python_type = self._yaml_type_to_python(field_type)
            if is_required:
                if self._is_nullable(rules):
                    python_type = self._as_optional_type(python_type)
                field_definitions[field_name] = (
                    python_type,
                    Field(..., **constraints),
                )
            else:
                if self._is_nullable(rules):
                    python_type = self._as_optional_type(python_type)
                field_definitions[field_name] = (
                    python_type,
                    Field(None, **constraints),
                )

            if "enum" in rules:
                validators[f"validate_enum_{field_name}"] = self._build_enum_validator(
                    field_name, rules["enum"]
                )

        return create_model(name, __validators__=validators, **field_definitions)

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
        profile_fields = self.schema["schemas"]["common_fields"].get("profile", {})
        model = self._create_section_model("Profile", profile_fields, list(mandatory_fields))
        return model or create_model("Profile")

    def _create_root_model(self) -> Optional[Type[BaseModel]]:
        """Build a Pydantic model for top-level (root) fields like 'dr_type'."""
        common_fields = self.schema["schemas"].get("common_fields", {})
        root_fields = {
            field_name: field_type
            for field_name, field_type in common_fields.items()
            if field_name not in ("profile", "metadata")
            and not isinstance(field_type, dict)
        }
        mandatory_fields = (
            self.schema["schemas"]
            .get("validations", {})
            .get("mandatory_fields", {})
            .get("root", [])
        )
        return self._create_section_model("Root", root_fields, list(mandatory_fields))

    def _create_metadata_model(self) -> Optional[Type[BaseModel]]:
        """Build a Pydantic model for the 'metadata' section of the DR."""
        metadata_fields = self.schema["schemas"]["common_fields"].get("metadata", {})
        mandatory_fields = (
            self.schema["schemas"]
            .get("validations", {})
            .get("mandatory_fields", {})
            .get("metadata", [])
        )
        return self._create_section_model(
            "Metadata", metadata_fields, list(mandatory_fields)
        )

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
        mandatory_fields = (
            self.schema["schemas"].get("validations", {}).get("mandatory_fields", {})
        )
        mandatory_data_fields = []
        if isinstance(mandatory_fields, dict):
            mandatory_data_fields = list(mandatory_fields.get("entity.data", []) or [])
            if not mandatory_data_fields:
                mandatory_data_fields = list(mandatory_fields.get("data", []) or [])
        field_definitions = {}
        validators = {}

        for field_name, field_type in data_fields.items():
            is_required = field_name in mandatory_data_fields
            rules = type_constraints.get(field_name, {})
            constraints = {}

            if "min" in rules:
                constraints["ge"] = rules["min"]
            if "max" in rules:
                constraints["le"] = rules["max"]

            if field_type == "List[Dict]":
                python_type = List[Dict[str, Any]]
                if self._is_nullable(rules):
                    python_type = self._as_optional_type(python_type)
                if is_required:
                    field_definitions[field_name] = (python_type, Field(...))
                else:
                    if self._is_nullable(rules):
                        field_definitions[field_name] = (python_type, Field(None))
                    else:
                        field_definitions[field_name] = (
                            python_type,
                            Field(default_factory=list),
                        )

                if "item_constraints" in rules:
                    item_rules = rules["item_constraints"]
                    required_fields = item_rules.get("required_fields", [])
                    type_mappings = item_rules.get("type_mappings", {})
                    validators[
                        f"validate_items_{field_name}"
                    ] = self._build_list_items_validator(
                        field_name, required_fields, type_mappings
                    )

            elif field_type == "List[str]":
                python_type = List[str]
                if self._is_nullable(rules):
                    python_type = self._as_optional_type(python_type)
                if is_required:
                    field_definitions[field_name] = (python_type, Field(...))
                else:
                    if self._is_nullable(rules):
                        field_definitions[field_name] = (python_type, Field(None))
                    else:
                        field_definitions[field_name] = (
                            python_type,
                            Field(default_factory=list),
                        )

            else:
                python_type = self._yaml_type_to_python(field_type)
                if self._is_nullable(rules):
                    python_type = self._as_optional_type(python_type)
                if is_required:
                    field_definitions[field_name] = (
                        python_type,
                        Field(..., **constraints),
                    )
                else:
                    if self._is_nullable(rules):
                        python_type = self._as_optional_type(python_type)
                    field_definitions[field_name] = (
                        python_type,
                        Field(None, **constraints),
                    )

            if "enum" in rules:
                validators[f"validate_enum_{field_name}"] = self._build_enum_validator(
                    field_name, rules["enum"]
                )

        model = create_model("Data", __validators__=validators, **field_definitions)
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
        RootModel = self._create_root_model()
        ProfileModel = self._create_profile_model()
        DataModel = self._create_data_model()
        MetadataModel = self._create_metadata_model()

        # Scaffold the DR with required fields and timestamps
        dr_dict = {
            "_id": str(uuid.uuid4()),
            "dr_type": dr_type,
            "metadata": {
                "created_at": datetime.utcnow(),
                "last_update": datetime.utcnow(),
            },
            "data": {},
        }

        # Apply initialisation defaults from the YAML template
        init_values = (
            self.schema["schemas"].get("validations", {}).get("initialization", {})
        )
        if "root" in init_values and "_id" in (init_values.get("root") or {}):
            raise ValueError("Initialization defaults must not set _id")
        data_fields = self.schema["schemas"].get("entity", {}).get("data", {})
        for section, defaults in init_values.items():
            if section == "root":
                dr_dict.update(defaults)
            elif section == "metadata":
                dr_dict["metadata"].update(defaults)
            elif section == "profile":
                # Profile defaults are merged into a 'profile' sub-dict
                dr_dict.setdefault("profile", {}).update(defaults)
            elif section in ["entity.data", "data"]:
                # Template-level data defaults
                dr_dict["data"].update(defaults)
            elif section in data_fields:
                dr_dict["data"][section] = defaults
            else:
                dr_dict[section] = defaults

        # Ensure discriminator matches the requested DR type
        dr_dict["dr_type"] = dr_type

        # Caller must not override the generated _id
        if "_id" in initial_data:
            raise ValueError("Caller must not provide _id")

        # Validate and merge profile data (defaults + caller values)
        profile_payload = dr_dict.get("profile", {})
        if "profile" in initial_data:
            profile_payload = {**profile_payload, **initial_data["profile"]}
        if ProfileModel is not None:
            profile = ProfileModel(**profile_payload)
            dr_dict["profile"] = profile.model_dump(exclude_unset=True)

        # Validate and merge entity data (defaults + caller values)
        data_payload = {**dr_dict["data"], **initial_data.get("data", {})}
        if DataModel is not None:
            data = DataModel(**data_payload)
            dr_dict["data"] = data.model_dump(exclude_unset=True)

        # Merge any extra metadata supplied by the caller
        if "metadata" in initial_data:
            dr_dict["metadata"].update(initial_data["metadata"])

        if MetadataModel is not None:
            metadata = MetadataModel(**dr_dict["metadata"])
            dr_dict["metadata"] = metadata.model_dump(exclude_unset=True)

        # Validate root fields (e.g., dr_type)
        if RootModel is not None:
            root_payload = {
                field: dr_dict.get(field) for field in RootModel.model_fields.keys()
            }
            root = RootModel(**root_payload)
            dr_dict.update(root.model_dump(exclude_unset=True))

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
        RootModel = self._create_root_model()
        ProfileModel = self._create_profile_model()
        DataModel = self._create_data_model()
        MetadataModel = self._create_metadata_model()

        updated_dr = dr.copy()
        updated_dr.setdefault("metadata", {})
        updated_dr.setdefault("data", {})

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
        updated_dr["metadata"]["last_update"] = datetime.utcnow()

        if MetadataModel is not None:
            metadata = MetadataModel(**updated_dr["metadata"])
            updated_dr["metadata"] = metadata.model_dump(exclude_unset=True)

        if RootModel is not None:
            root_payload = {
                field: updated_dr.get(field) for field in RootModel.model_fields.keys()
            }
            root = RootModel(**root_payload)
            updated_dr.update(root.model_dump(exclude_unset=True))

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
