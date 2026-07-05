"""
DT Factory Module
==================
Factory class for creating, persisting, and reconstituting Digital Twin instances.

Architecture reasoning (from the lecture):
- The DTFactory bridges the persistence layer (MongoDB via DatabaseService) and the
  in-memory DigitalTwin object.
- Creating a DT writes a lightweight "manifest" document to MongoDB that stores:
    • name & description
    • references to Digital Replicas (type + id pairs)
    • references to attached services (name + config)
    • metadata (timestamps, status)
- When a DT needs to be *used* (e.g. to run a service), the factory reconstitutes
  a live DigitalTwin object by:
    1. Loading the manifest from MongoDB.
    2. Fetching each referenced DR from its type-specific collection.
    3. Dynamically importing and instantiating each referenced service class.
- The service module mapping (`_get_service_module_mapping`) is the single place
  where service class names are mapped to their Python module paths. To register a
  new service, you only add one entry here.
"""

from typing import Dict, List, Optional, Type, Any, Union, get_args, get_origin
from datetime import datetime, timezone
from bson import ObjectId
import uuid
import pymongo.collection
import yaml
from pydantic import BaseModel, create_model, Field, field_validator
from cloud_platform.services.database_service import DatabaseService
from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry
from cloud_platform.digital_twin.core import DigitalTwin
import logging
logger = logging.getLogger(__name__)

class DTFactory:
    """
    Factory for creating and managing Digital Twin documents in MongoDB,
    and for reconstituting live DigitalTwin instances from stored data.
    """
    

    @staticmethod
    def _add_sensor_replica(dt_id: str, dt_collection: pymongo.collection.Collection, sensor: dict) -> None:
        """
        Add a sensor replica to an existing DT manifest.

        Args:
            dt_id:   Digital Twin _id.
            dt_collection: pymongo.collection.Collection
            sensor:  Sensor dict
            {
                "dr_type": dr_entry.get("profile", {}).get("device_type"),
                "device_id": device_id, e.g., "AABBCCDD-t1", "actuator-002"
                "device_type": device_type, e.g., "t1", "t2", "None"
                "current_value": str(device_data.get("value"))+" "+UNIT_MAP.get(device_id.split("-")[1], "NOT_SPECIFIED"),
                "threshold": str(device_data.get("threshold"))+" "+UNIT_MAP.get(device_id.split("-")[1], "NOT_SPECIFIED"),
                "alert_level": alert_level,
            }
        """
        try:
            # Try to update an existing sensor entry (match by _id_document)
            res = dt_collection.update_one(
                {"_id": dt_id, "sensors._id_document": sensor.get("_id_document")},
                {"$set": {
                    "sensors.$.dr_type": sensor.get("dr_type"),
                    "sensors.$.device_id": sensor.get("device_id"),
                    "sensors.$.device_type": sensor.get("device_type"),
                    "sensors.$.current_value": sensor.get("current_value"),
                    "sensors.$.threshold": sensor.get("threshold"),
                    "sensors.$.alert_level": sensor.get("alert_level"),
                }}
            )

            if res.matched_count == 0:
                # Not present → push new entry
                dt_collection.update_one(
                    {"_id": dt_id},
                    {"$push": {"sensors": {
                        "_id_document": sensor.get("_id_document"),
                        "dr_type": sensor.get("dr_type"),
                        "device_id": sensor.get("device_id"),
                        "device_type": sensor.get("device_type"),
                        "current_value": sensor.get("current_value"),
                        "threshold": sensor.get("threshold"),
                        "alert_level": sensor.get("alert_level"),
                    }}}
                )
        except Exception as e:
            raise Exception(f"Failed to add Digital Replica: {str(e)}") 
    @staticmethod
    def _add_actuator_replica(dt_id: str, dt_collection: pymongo.collection.Collection, actuator: dict) -> None:
        pass
    
    @staticmethod
    def _add_gateway_replica(dt_id: str, dt_collection: pymongo.collection.Collection, gateway: dict) -> None:
        pass

    ADD_FUNCTIONS = {
            "gateway": _add_gateway_replica,
            "sensor": _add_sensor_replica,
            "actuator": _add_actuator_replica,
        }

    ## Keep a static mapping of implemented service names to their module paths for dynamic import
    IMPLEMENTED_SERVICES = {
        "AlertingService": "cloud_platform.services.analytics",
    }

    def __init__(self, name: str, db_service: DatabaseService, schema_registry: SchemaRegistry, dt_schema_path: str = None):
        self.db_service = db_service
        self.schema_registry = schema_registry
        self.dt_id = None # unique identifier of the DT document in MongoDB (set after creation -- create_dt() -- or after reconstitution -- create_dt_from_data())
        self._registered_services = {}  # [{class:service_name, config: config, status:active},   ....] 
        self.name = name

        # Load the DT YAML schema (similar to DRFactory)
        if dt_schema_path is None:
            # Default path: assumes digital_twin.yaml is in the templates folder
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            dt_schema_path = os.path.join(base_dir, "cloud_platform", "virtualization", "templates", "digital_twin.yaml")
        
        self.dt_schema = self._load_schema(dt_schema_path)
        
        # Ensure the DT collection exists with proper indexes
        self._init_dt_collection()
        self.create_dt()
        self._init_dt_services()


    # ── Schema loading ────────────────────────────────────────────────

    def _load_schema(self, path: str) -> Dict:
        """Load and parse the YAML template file."""
        try:
            with open(path, "r") as file:
                return yaml.safe_load(file)
        except Exception as e:
            raise ValueError(f"Failed to load DT schema: {str(e)}")

    # ── Pydantic model helpers ────────────────────────────────────────

    @staticmethod
    def _as_optional_type(python_type):
        """Normalize to Optional[T] without nesting Optional[Optional[T]]."""
        origin = get_origin(python_type)
        if origin is Union and type(None) in get_args(python_type):
            return python_type
        return Optional[python_type]

    @staticmethod
    def _is_nullable(rules: Dict[str, Any]) -> bool:
        return rules.get("nullable") is True or rules.get("type") == "nullable"

    @staticmethod
    def _yaml_type_to_python(yaml_type):
        """Map a YAML type string (or structure) to the corresponding Python type."""
        # Handle non-string types (e.g., list/dict structures from YAML)
        if not isinstance(yaml_type, str):
            return Any
        
        mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "datetime": datetime,
            "List[str]": List[str],
            "List[Dict]": List[Dict[str, Any]],
        }
        return mapping.get(yaml_type, Any)

    @staticmethod
    def _build_enum_validator(field_name: str, enum_values: List[Any]):
        """Build a field validator for enum constraints."""
        @field_validator(field_name)
        def _validate_enum(cls, value, enum_values=tuple(enum_values), field_name=field_name):
            if value is None:
                return value
            if value not in enum_values:
                raise ValueError(f"{field_name} must be one of {list(enum_values)}")
            return value

        return _validate_enum

    def _create_section_model(
        self, name: str, fields: Dict[str, Any], mandatory_fields: List[str]
    ) -> Optional[Type[BaseModel]]:
        """Build a Pydantic model for a section of the DT schema."""
        if not fields:
            return None

        type_constraints = (
            self.dt_schema["schemas"].get("validations", {}).get("type_constraints", {})
        )
        
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

    def _create_metadata_model(self) -> Optional[Type[BaseModel]]:
        """Build a Pydantic model for the 'metadata' section."""
        metadata_fields = self.dt_schema["schemas"]["common_fields"].get("metadata", {})
        mandatory_fields = (
            self.dt_schema["schemas"]
            .get("validations", {})
            .get("mandatory_fields", {})
            .get("metadata", [])
        )
        return self._create_section_model(
            "Metadata", metadata_fields, list(mandatory_fields)
        )

    def _create_root_model(self) -> Optional[Type[BaseModel]]:
        """Build a Pydantic model for top-level (root) fields like 'name', 'description'."""
        common_fields = self.dt_schema["schemas"].get("common_fields", {})
        root_fields = {
            field_name: field_type
            for field_name, field_type in common_fields.items()
            if field_name not in ("metadata", "_id")
            and not isinstance(field_type, (dict, list))
        }
        mandatory_fields = (
            self.dt_schema["schemas"]
            .get("validations", {})
            .get("mandatory_fields", {})
            .get("root", [])
        )
        return self._create_section_model("Root", root_fields, list(mandatory_fields))

    # ── DT CRUD ───────────────────────────────────────────────────────

    def create_dt(self, description: str = None, initial_data: Dict[str, Any] = None) -> str:
        """
        Create a new Digital Twin manifest in MongoDB using YAML schema-based validation.
        If a DT with the same unique `name` already exists, return its _id instead of creating a duplicate.

        Steps:
            1. Build Pydantic models from the YAML schema.
            2. Initialize the DT dict with a UUID _id and timestamps.
            3. Apply default values from the 'initialization' section.
            4. Merge and validate the caller-supplied data.
            5. Store the complete DT document in MongoDB.

        Args:
            name:         Human-readable name (optional, can come from initial_data).
            description:  Optional description (can come from initial_data).
            initial_data: Optional dict with 'name', 'description', and other fields.

        Returns:
            The string _id of the created DT document.
        """
        # Build Pydantic models from the YAML schema
        RootModel = self._create_root_model()
        MetadataModel = self._create_metadata_model()

        # Scaffold the DT with required fields and timestamps
        dt_dict = {
            "_id": str(uuid.uuid4()),
            "digital_replicas": [],
            "services": [],
            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        # Apply initialization defaults from the YAML template
        init_values = (
            self.dt_schema["schemas"].get("validations", {}).get("initialization", {})
        )
        
        for section, defaults in init_values.items():
            if section == "root":
                dt_dict.update(defaults)
            elif section == "metadata":
                dt_dict["metadata"].update(defaults)

        # Merge caller-supplied name and description (prioritize parameters over initial_data)
        if initial_data is None:
            initial_data = {}
        
        if self.name is not None:
            initial_data["name"] = self.name
        if description is not None:
            initial_data["description"] = description

        # Validate and merge root fields (name, description, services, digital_replicas)
        root_payload = {
            k: dt_dict.get(k, initial_data.get(k))
            for k in ["name", "description", "services", "digital_replicas"]
        }
        
        # Merge caller-supplied root data
        root_payload.update({k: v for k, v in initial_data.items() 
                            if k in ["name", "description", "services", "digital_replicas"]})
        
        if RootModel is not None:
            try:
                root = RootModel(**root_payload)
                dt_dict.update(root.model_dump(exclude_unset=True))
            except Exception as e:
                raise ValueError(f"Failed to validate root fields: {str(e)}")

        # Validate and merge metadata
        metadata_payload = {**dt_dict.get("metadata", {})}
        if "metadata" in initial_data:
            metadata_payload.update(initial_data["metadata"])
        
        if MetadataModel is not None:
            try:
                metadata = MetadataModel(**metadata_payload)
                dt_dict["metadata"] = metadata.model_dump(exclude_unset=True)
            except Exception as e:
                raise ValueError(f"Failed to validate metadata: {str(e)}")

        # Ensure _id is never overridden by caller
        if "_id" in initial_data:
            raise ValueError("Caller must not provide _id")

        # Persist to MongoDB. If a DT with the same unique `name` exists,
        # return its id instead of failing — this mirrors expected "find-or-create" behaviour.
        try:
            dt_collection = self.db_service.db["digital_twins"]
            result = dt_collection.insert_one(dt_dict)
            self.dt_id = str(result.inserted_id)
            return self.dt_id
        except Exception as e:
            # Handle DuplicateKeyError (unique index on `name`) by returning existing DT
            try:
                from pymongo.errors import DuplicateKeyError
            except Exception:
                DuplicateKeyError = None

            if DuplicateKeyError and isinstance(e, DuplicateKeyError):
                # Find existing document by name and return its id
                existing = dt_collection.find_one({"name": dt_dict.get("name")})
                if existing:
                    self.dt_id = str(existing.get("_id"))
                    return self.dt_id

            # For any other error, propagate
            raise Exception(f"Failed to create Digital Twin: {str(e)}")

    def get_dt(self, dt_id: str) -> Optional[Dict]:
        """
        Retrieve a DT manifest by _id.

        Returns:
            The DT document dict, or None if not found.
        """
        try:
            dt_collection = self.db_service.db["digital_twins"]
            return dt_collection.find_one({"_id": dt_id})
        except Exception as e:
            raise Exception(f"Failed to get Digital Twin: {str(e)}")

    def list_dts(self) -> List[Dict]:
        """Return all DT manifests."""
        try:
            dt_collection = self.db_service.db["digital_twins"]
            return list(dt_collection.find())
        except Exception as e:
            raise Exception(f"Failed to list Digital Twins: {str(e)}")

    # ── Digital Replica management ────────────────────────────────────

    def add_digital_replicas(self, dt_id: str, dr_refs: List[Dict[str, str]]) -> None:
        """
        Add multiple DR references to an existing DT manifest.

        Args:
            dt_id:   Digital Twin _id.
            dr_refs: List of DR reference dicts, each with 'type' and 'id'.
        """
        
        try:
            dt_collection = self.db_service.db["digital_twins"]
            digital_twin = dt_collection.find_one({"_id": dt_id})

            if not digital_twin:
                raise ValueError(f"Digital Twin not found: {dt_id}")
            
            for dr_ref in dr_refs:
                if "_id_document" not in dr_ref or "dr_type" not in dr_ref or "device_id" not in dr_ref:
                    raise ValueError(f"Invalid DR reference: {dr_ref}. Must contain '_id_document', 'dr_type', and 'device_id'.")

                if dr_ref["dr_type"] in self.ADD_FUNCTIONS:
                    self.ADD_FUNCTIONS[dr_ref["dr_type"]](dt_id, dt_collection, dr_ref)
                else:
                    logger.error(f"Unknown DR type: {dr_ref['dr_type']}")
                    continue  # Skip unknown DR types
        except Exception as e:
            raise Exception(f"Failed to add multiple Digital Replicas: {str(e)}")
        finally:
            try:
                # Finally update the timestamp
                dt_collection.update_one(
                    {"_id": dt_id},
                    {
                        "$set": {
                            "metadata.updated_at": datetime.now(timezone.utc).isoformat()
                        },
                    },
                )
            except Exception as e:
                raise Exception(f"Failed to update timestamp after adding Digital Replicas: {str(e)}")    
    
    def add_actuator_replicas(self, dt_id: str, actuators: List[dict]) -> None:
        '''
        Add multiple actuator replicas to an existing DT manifest.
        Args:
            dt_id:   Digital Twin _id.
            actuators: List of actuator dicts (each with 'dr_type', 'device_id', etc.).
        '''
        try:
            # Verify the Collection exists before creating the reference
            # the digital replica is stored in another collection and we only add reference here

            ## 1. Check if the database service is connected
            if self.db_service is None or not self.db_service.is_connected():
                logger.error("Database service is not connected. Cannot add actuator replica.")
                raise ConnectionError("Database service not connected")
            
            # 2. Check if the DT collection exists
            dt_collection = self.db_service.db["digital_twins"]
            digital_twin = dt_collection.find_one({"_id": dt_id})

            if not digital_twin:
                logger.warning(f"Digital Twin with id {dt_id} not found. Cannot add sensor replica.")
                raise ValueError(f"Digital Twin not found: {dt_id}")
            
            # 3. Add/update each sensor replica
            for actuator in actuators:
                self._add_actuator_replica(dt_id, dt_collection, actuator)
        except Exception as e:
            raise Exception(f"Failed to add multiple actuator replicas: {str(e)}")
        finally:
            try:
                # Finally update the timestamp
                dt_collection.update_one(
                    {"_id": dt_id},
                    {
                        "$set": {
                            "metadata.updated_at": datetime.now(timezone.utc).isoformat()
                        },
                    },
                )
            except Exception as e:
                raise Exception(f"Failed to update timestamp after adding actuator replicas: {str(e)}")

    def _get_service_module_mapping(self) -> Dict[str, Dict[str, Any]]:
        """
        Return the mapping of service class names to their Python module paths.

        This is the ONLY place you need to edit when adding a new service to the
        system. The dynamic import in add_service() and create_dt_from_data()
        relies on this mapping.
        """
        return self._registered_services

    # ── Service management ────────────────────────────────────────────
    def _init_dt_services(self):
        '''
        Look at the dt services in the DT manifest and load them in the cache memory for quicker access
        '''
        try:
            dt_collection = self.db_service.db["digital_twins"]

            dt = dt_collection.find_one(
                {"_id": self.dt_id},
            )
            if not dt:
                raise ValueError(f"Digital Twin not found: {dt_id}")
            for service in dt.get("services", []):

                service_name = str(service.get("name")) # used to resolve the class
                if service_name not in __class__.IMPLEMENTED_SERVICES:
                    continue

                service_state = str(service.get("status")).lower()
                if service_state != "active":
                    logger.info(f"inactive state detected:{service_name}")
                    continue
                
                service_config = dict(service.get("config")) # used to initialize the object


                module_name = __class__.IMPLEMENTED_SERVICES[service_name]

                # Validate that the service can be imported and instantiated
                service_module = __import__(module_name, fromlist=[service_name])
                service_class = getattr(service_module, service_name)

                # finally add it to the _registered_services list
                self._registered_services[service_name] = {"class" : service_class, "config": service_config}

        except Exception as e:
            raise Exception(f"Failed to add service: {str(e)}")
        
    def get_services(self) -> List[Any]:
        """
        Instantiate the service classes currently registered in this factory.

        Returns:
            A list of service instances created from the classes cached in
            ``self._registered_services``.
        """
        temp = []
        for service in self._registered_services.values():
            class_ref = service.get("class")
            configuration = service.get("config")
            obj = class_ref(config = configuration)
            temp.append(obj)
        return temp

    def add_service(self, dt_id: str, service_name: str, service_config: Dict = {}) -> None:
        """
        Register a service with a DT by writing a service descriptor to its manifest.

        The method validates that the service class can actually be imported and
        instantiated before persisting the reference — fail-fast principle.

        Args:
            dt_id:          Digital Twin _id.
            service_name:   Class name of the service (must exist in the module mapping).
            service_config: Optional configuration dict passed to the service.
        """
        try:
            dt_collection = self.db_service.db["digital_twins"]

            # Look up the module path from the mapping
            if service_name not in __class__.IMPLEMENTED_SERVICES:
                raise ValueError(
                    f"Service '{service_name}' not configured in module mapping. "
                    f"Available: {list(__class__.IMPLEMENTED_SERVICES.keys())}"
                )

            module_name = __class__.IMPLEMENTED_SERVICES[service_name]

            try:
                # Validate that the service can be imported and instantiated
                service_module = __import__(module_name, fromlist=[service_name])
                service_class = getattr(service_module, service_name)
                _ = service_class()  # smoke test instantiation
            except (ImportError, AttributeError) as e:
                raise ValueError(
                    f"Failed to load service '{service_name}' from module "
                    f"'{module_name}': {str(e)}"
                )

            service_data = {
                "name": service_name,
                "config": service_config or {},
                "status": "active",
                "added_at": datetime.now().isoformat(),
            }

            dt_collection.update_one(
                {"_id": dt_id},
                {
                    "$push": {"services": service_data},
                    "$set": {"metadata.updated_at": datetime.now().isoformat()},
                },
            )
            self._registered_services[service_name] = service_class  # cache the class for later use
        except Exception as e:
            raise Exception(f"Failed to add service: {str(e)}")

    def remove_service(self, dt_id: str, service_name: str) -> None:
        """
        Remove a service from a DT by deleting its descriptor from the manifest.

        Args:
            dt_id:        Digital Twin _id.
            service_name: Class name of the service to remove.
        """
        try:
            dt_collection = self.db_service.db["digital_twins"]
            dt_collection.update_one(
                {"_id": dt_id},
                {
                    "$pull": {"services": {"name": service_name}},
                    "$set": {"metadata.updated_at": datetime.now().isoformat()},
                },
            )
            self._registered_services.pop(service_name, None)  # remove from cache if present
        except Exception as e:
            raise Exception(f"Failed to remove service: {str(e)}")
    # ── DT instance reconstitution ────────────────────────────────────

    def create_dt_from_data(self, dt_data: dict) -> DigitalTwin:
        """
        Reconstitute a live DigitalTwin object from a stored manifest.

        Process:
            1. Create an empty DigitalTwin.
            2. For each DR reference in the manifest, fetch the DR from the DB
               and add it to the DT.
            3. For each service descriptor, dynamically import and instantiate
               the service class, optionally configuring it if it has a
               configure() method.

        Args:
            dt_data: The DT manifest dict (as returned by get_dt()).

        Returns:
            A fully populated DigitalTwin instance ready for service execution.
        """
        print(f"\n=== Creating DT Instance for '{dt_data.get('name', 'unnamed')}' ===")
        try:
            dt = DigitalTwin()

            # ── Load Digital Replicas ──
            for dr_ref in dt_data.get("digital_replicas", []):
                dr = self.db_service.get_dr(dr_ref["type"], dr_ref["id"])
                if dr:
                    dt.add_digital_replica(dr)
                    print(f"  Loaded DR: type={dr_ref['type']}, id={dr_ref['id']}")

            # ── Load and instantiate Services ──
            service_mapping = self._get_service_module_mapping()

            for service_desc in dt_data.get("services", []):
                service_name = service_desc["name"]

                if service_name in service_mapping:
                    try:
                        module_name = service_mapping[service_name]
                        service_module = __import__(module_name, fromlist=[service_name])
                        service_class = getattr(service_module, service_name)
                        service = service_class()

                        # If the service supports runtime configuration, apply it
                        if hasattr(service, "configure") and "config" in service_desc:
                            service.configure(service_desc["config"])

                        dt.add_service(service)
                        print(f"  Loaded service: {service_name}")
                    except Exception as e:
                        print(f"  WARNING: Failed to load service '{service_name}': {e}")
                else:
                    print(f"  WARNING: Service '{service_name}' not in module mapping")

            print(f"=== DT ready — {len(dt.digital_replicas)} DRs, "
                  f"{len(dt.active_services)} services ===\n")
            return dt

        except Exception as e:
            raise Exception(f"Failed to create DT from data: {str(e)}")

    def get_dt_instance(self, dt_id: str) -> Optional[DigitalTwin]:
        """
        Convenience method: fetch a DT manifest by id and return a live instance.

        Returns:
            A DigitalTwin instance, or None if the DT was not found.
        """
        try:
            dt_data = self.get_dt(dt_id)
            if not dt_data:
                return None
            return self.create_dt_from_data(dt_data)
        except Exception as e:
            raise Exception(f"Failed to get DT instance: {str(e)}")

    # ── Collection initialisation ─────────────────────────────────────

    def _init_dt_collection(self) -> None:
        """
        Ensure the 'digital_twins' collection exists with useful indexes.

        Called once at startup. The unique index on 'name' prevents duplicate DTs.
        """
        if not self.db_service.is_connected():
            raise ConnectionError("Database service not connected")

        try:
            db = self.db_service.db
            if "digital_twins" not in db.list_collection_names():
                db.create_collection("digital_twins")
                dt_collection = db["digital_twins"]
                dt_collection.create_index("name", unique=True)
                dt_collection.create_index("metadata.created_at")
                dt_collection.create_index("metadata.updated_at")
        except Exception as e:
            raise Exception(f"Failed to initialize DT collection: {str(e)}")