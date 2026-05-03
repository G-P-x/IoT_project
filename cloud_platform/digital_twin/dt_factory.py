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

from typing import Dict, List, Optional
from datetime import datetime
from bson import ObjectId
from cloud_platform.services.database_service import DatabaseService
from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry
from cloud_platform.digital_twin.core import DigitalTwin


class DTFactory:
    """
    Factory for creating and managing Digital Twin documents in MongoDB,
    and for reconstituting live DigitalTwin instances from stored data.
    """

    def __init__(self, db_service: DatabaseService, schema_registry: SchemaRegistry):
        self.db_service = db_service
        self.schema_registry = schema_registry
        # Ensure the DT collection exists with proper indexes
        self._init_dt_collection()

    # ── DT CRUD ───────────────────────────────────────────────────────

    def create_dt(self, name: str, description: str = "") -> str:
        """
        Create a new Digital Twin manifest in MongoDB.

        The manifest starts with empty DR and service lists; they are populated
        later via add_digital_replica() and add_service().

        Args:
            name:        Human-readable name (unique index).
            description: Optional description.

        Returns:
            The string _id of the created DT document.
        """
        dt_data = {
            "_id": str(ObjectId()),
            "name": name,
            "description": description,
            "digital_replicas": [],  # List of {type, id} references
            "services": [],          # List of service descriptors
            "metadata": {
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "status": "active",
            },
        }

        try:
            dt_collection = self.db_service.db["digital_twins"]
            result = dt_collection.insert_one(dt_data)
            return str(result.inserted_id)
        except Exception as e:
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

    def add_digital_replica(self, dt_id: str, dr_type: str, dr_id: str) -> None:
        """
        Add a DR reference to an existing DT manifest.

        Before adding, the method verifies that the DR actually exists in the
        database — this prevents dangling references.

        Args:
            dt_id:   Digital Twin _id.
            dr_type: DR type (e.g. 'gateway', 'sensor').
            dr_id:   DR _id.
        """
        try:
            dt_collection = self.db_service.db["digital_twins"]

            # Verify the DR exists before creating the reference
            dr = self.db_service.get_dr(dr_type, dr_id)
            if not dr:
                raise ValueError(f"Digital Replica not found: {dr_id}")

            # Atomically push the reference into the DT document
            dt_collection.update_one(
                {"_id": dt_id},
                {
                    "$push": {
                        "digital_replicas": {"type": dr_type, "id": dr_id}
                    },
                    "$set": {
                        "metadata.updated_at": datetime.utcnow()
                    },
                },
            )
        except Exception as e:
            raise Exception(f"Failed to add Digital Replica: {str(e)}")

    # ── Service management ────────────────────────────────────────────

    def _get_service_module_mapping(self) -> Dict[str, str]:
        """
        Return the mapping of service class names to their Python module paths.

        This is the ONLY place you need to edit when adding a new service to the
        system. The dynamic import in add_service() and create_dt_from_data()
        relies on this mapping.
        """
        return {
            "AggregationService": "cloud_platform.services.analytics",
            # Add new services here, e.g.:
            # "AnomalyDetectionService": "cloud_platform.services.anomaly_detection",
        }

    def add_service(self, dt_id: str, service_name: str, service_config: Dict = None) -> None:
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
            module_mapping = self._get_service_module_mapping()
            if service_name not in module_mapping:
                raise ValueError(
                    f"Service '{service_name}' not configured in module mapping. "
                    f"Available: {list(module_mapping.keys())}"
                )

            module_name = module_mapping[service_name]

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
                "added_at": datetime.utcnow(),
            }

            dt_collection.update_one(
                {"_id": dt_id},
                {
                    "$push": {"services": service_data},
                    "$set": {"metadata.updated_at": datetime.utcnow()},
                },
            )
        except Exception as e:
            raise Exception(f"Failed to add service: {str(e)}")

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
