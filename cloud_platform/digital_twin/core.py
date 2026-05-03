"""
Digital Twin Core Module
========================
This module implements the core Digital Twin (DT) class following the same pattern
as the lecture's architecture.

Architecture reasoning:
- A Digital Twin is a virtual representation of a physical entity (in our case, the
  Mt. Etna monitoring system or a specific monitoring station).
- It aggregates multiple Digital Replicas (DRs), each representing a physical component
  (e.g. a gateway device or a sensor).
- Services can be dynamically attached to a DT to perform analytics, predictions, etc.
- The DT acts as an orchestrator: it holds references to DRs and delegates processing
  to its active services, passing the relevant DR data to them.

This mirrors the lecture's DigitalTwin class, which stores a list of DRs and a dict
of services, and exposes an execute_service() method that feeds DR data into a chosen
service for processing.
"""

from typing import Dict, List, Any
from cloud_platform.services.base import BaseService


class DigitalTwin:
    """
    Core Digital Twin class that manages Digital Replicas (DRs) and services.

    Design rationale (from the lecture pattern):
        - `digital_replicas` is a flat list of DR dicts. Each DR has a 'type' field
          (e.g. 'gateway', 'sensor') so services can filter by type.
        - `active_services` maps a service name to its instance. Services follow the
          BaseService interface so they can be swapped/added at runtime.
    """

    def __init__(self):
        # List of DR dictionaries — each dict is the full DR document as stored in MongoDB.
        # Keeping them as plain dicts (instead of ORM objects) maximises flexibility and
        # avoids coupling the DT core to a specific persistence layer.
        self.digital_replicas: List[Dict] = []

        # Maps service_name → service_instance.
        # Using a dict ensures O(1) lookup when executing a service by name.
        self.active_services: Dict[str, BaseService] = {}

    # ── Digital Replica management ────────────────────────────────────

    def add_digital_replica(self, dr_instance: Dict) -> None:
        """
        Add a Digital Replica to this twin.

        Args:
            dr_instance: A DR document dict (as returned by DatabaseService.get_dr).
        """
        self.digital_replicas.append(dr_instance)

    # ── Service management ────────────────────────────────────────────

    def add_service(self, service) -> None:
        """
        Register a service with this Digital Twin.

        Accepts either a service *instance* or a service *class*.
        If a class is passed it is instantiated with no arguments — this keeps the
        API flexible (callers can pre-configure or let the DT handle instantiation).
        """
        if isinstance(service, type):
            # If a class reference is passed, instantiate it first
            service = service()
        self.active_services[service.name] = service

    def list_services(self) -> List[str]:
        """Return the names of all currently attached services."""
        return list(self.active_services.keys())

    def remove_service(self, service_name: str) -> None:
        """Detach a named service from this DT."""
        if service_name in self.active_services:
            del self.active_services[service_name]

    # ── Data access ───────────────────────────────────────────────────

    def get_dt_data(self) -> Dict:
        """
        Return the full DT state as a dict.

        The 'digital_replicas' key is the contract that services rely on when they
        receive data via execute_service().
        """
        return {
            "digital_replicas": self.digital_replicas
        }

    # ── Service execution ─────────────────────────────────────────────

    def execute_service(self, service_name: str, **kwargs) -> Any:
        """
        Execute a named service, passing all DR data plus any extra keyword arguments.

        This is the main entry point for running analytics or processing on the DT.
        The pattern is identical to the lecture: build a data dict containing all DRs,
        then delegate to the service's execute() method.

        Args:
            service_name: Name of the registered service to run.
            **kwargs:     Extra parameters forwarded to the service (e.g. dr_type,
                          attribute, sensor_id, …).

        Returns:
            Whatever the service's execute() method returns.

        Raises:
            ValueError: If the requested service is not registered.
        """
        if service_name not in self.active_services:
            raise ValueError(f"Service '{service_name}' not found. "
                             f"Available: {self.list_services()}")

        service = self.active_services[service_name]

        # Package the DT's DR data in the format expected by all services
        data = {
            "digital_replicas": self.digital_replicas
        }

        return service.execute(data, **kwargs)

    def execute_service_on_dr(self, service_name: str, dr: Dict) -> Any:
        """
        Execute a service with the data of a single DR only.

        Useful when you want analytics scoped to one specific replica.

        Raises:
            ValueError: If the DR is not part of this DT.
        """
        if dr not in self.digital_replicas:
            raise ValueError("This DR is not part of this Digital Twin")

        data = dr.get("data", {})
        return self.execute_service(service_name, data=data)
