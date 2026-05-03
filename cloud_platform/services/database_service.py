"""
Database Service Module
========================
Provides a MongoDB persistence layer for Digital Replicas and Digital Twins.

Architecture reasoning (from the lecture):
- This service encapsulates ALL database interactions (connect, CRUD for DRs).
- It delegates schema validation to the SchemaRegistry so that the DB layer
  remains type-agnostic: adding a new DR type only requires a new YAML template
  — no changes in this file.
- Collection names are derived automatically via the SchemaRegistry
  (`<dr_type>_collection`), keeping the mapping consistent.
- The service stores a reference to the SchemaRegistry at init time so that
  save/get/query/update/delete operations can look up the correct collection
  and validation rules without any DR-type-specific logic.
"""

from typing import Dict, List, Optional
from pymongo import MongoClient
from datetime import datetime
from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry


class DatabaseService:
    """
    MongoDB wrapper used by the DT Factory and the application APIs.

    Lifecycle:
        1. Instantiate with connection string, db name, and a populated SchemaRegistry.
        2. Call connect() once at startup.
        3. Use save_dr / get_dr / query_drs / update_dr / delete_dr throughout.
        4. Call disconnect() on shutdown.
    """

    def __init__(self, connection_string: str, db_name: str, schema_registry: SchemaRegistry):
        self.connection_string = connection_string
        self.db_name = db_name
        self.schema_registry = schema_registry
        # MongoClient and Database references — populated by connect()
        self.client = None
        self.db = None

    # ── Connection management ─────────────────────────────────────────

    def connect(self) -> None:
        """
        Open a connection to MongoDB and select the target database.

        Raises:
            ConnectionError: If the client cannot reach the MongoDB server.
        """
        try:
            self.client = MongoClient(self.connection_string)
            self.db = self.client[self.db_name]
        except Exception as e:
            raise ConnectionError(f"Failed to connect to MongoDB: {str(e)}")

    def disconnect(self) -> None:
        """Gracefully close the MongoDB connection."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None

    def is_connected(self) -> bool:
        """Check whether the client is currently connected."""
        return self.client is not None and self.db is not None

    # ── CRUD for Digital Replicas ─────────────────────────────────────

    def save_dr(self, dr_type: str, dr_data: Dict) -> str:
        """
        Persist a new Digital Replica document.

        The collection is chosen via the SchemaRegistry so that all DRs of the
        same type end up in the same collection (e.g. 'gateway_collection').

        Args:
            dr_type: The DR type key (e.g. 'gateway', 'sensor').
            dr_data: The full DR document dict (including '_id').

        Returns:
            The string _id of the inserted document.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to MongoDB")

        try:
            # SchemaRegistry resolves type → collection name
            collection_name = self.schema_registry.get_collection_name(dr_type)
            collection = self.db[collection_name]
            collection.insert_one(dr_data)
            return str(dr_data["_id"])
        except Exception as e:
            raise Exception(f"Failed to save Digital Replica: {str(e)}")

    def get_dr(self, dr_type: str, dr_id: str) -> Optional[Dict]:
        """
        Retrieve a single DR by type and id.

        Returns:
            The DR document dict, or None if not found.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to MongoDB")

        try:
            collection_name = self.schema_registry.get_collection_name(dr_type)
            return self.db[collection_name].find_one({"_id": dr_id})
        except Exception as e:
            raise Exception(f"Failed to get Digital Replica: {str(e)}")

    def query_drs(self, dr_type: str, query: Dict = None) -> List[Dict]:
        """
        Query DRs of a given type with an optional MongoDB filter.

        Args:
            dr_type: DR type key.
            query:   Optional MongoDB query dict.  Pass {} or None for all.

        Returns:
            A list of matching DR document dicts.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to MongoDB")

        try:
            collection_name = self.schema_registry.get_collection_name(dr_type)
            return list(self.db[collection_name].find(query or {}))
        except Exception as e:
            raise Exception(f"Failed to query Digital Replicas: {str(e)}")

    def update_dr(self, dr_type: str, dr_id: str, update_data: Dict) -> None:
        """
        Partially update a DR document using MongoDB $set.

        The metadata.updated_at timestamp is always refreshed automatically.

        Args:
            dr_type:     DR type key.
            dr_id:       The _id of the DR to update.
            update_data: Dict of fields to set (can be nested).

        Raises:
            ValueError: If no document matched the given dr_id.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to MongoDB")

        try:
            collection_name = self.schema_registry.get_collection_name(dr_type)

            # Always bump the updated_at timestamp
            if "metadata" not in update_data:
                update_data["metadata"] = {}
            update_data["metadata"]["updated_at"] = datetime.utcnow()

            result = self.db[collection_name].update_one(
                {"_id": dr_id},
                {"$set": update_data}
            )

            if result.matched_count == 0:
                raise ValueError(f"Digital Replica not found: {dr_id}")
        except Exception as e:
            raise Exception(f"Failed to update Digital Replica: {str(e)}")

    def delete_dr(self, dr_type: str, dr_id: str) -> None:
        """
        Delete a DR document by type and id.

        Raises:
            ValueError: If no document matched the given dr_id.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to MongoDB")

        try:
            collection_name = self.schema_registry.get_collection_name(dr_type)
            result = self.db[collection_name].delete_one({"_id": dr_id})

            if result.deleted_count == 0:
                raise ValueError(f"Digital Replica not found: {dr_id}")
        except Exception as e:
            raise Exception(f"Failed to delete Digital Replica: {str(e)}")
