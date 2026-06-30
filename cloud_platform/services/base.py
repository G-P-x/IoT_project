"""
Base Service Module
====================
Defines the abstract base class that every service in the service pool must inherit.

Architecture reasoning (from the lecture):
- The services layer follows the Strategy / Plugin pattern: each service is a
  self-contained unit with a standardised interface (`execute`).
- By enforcing an ABC, we guarantee that every concrete service (analytics,
  predictions, database ops, …) can be used interchangeably by the Digital Twin
  core's `execute_service()` method.
- The `name` attribute is set automatically from the class name so that services
  are registered in the DT under a human-readable key without manual wiring.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseService(ABC):
    """
    Abstract base class for all services attached to a Digital Twin.

    Every concrete service must:
        1. Inherit from BaseService.
        2. Implement the `execute()` method.

    The DT core calls `service.execute(data, **kwargs)` where `data` always
    contains a 'digital_replicas' key with the full list of DR dicts.
    """

    def __init__(self):
        # Automatically derive the service name from the class name.
        # This avoids boilerplate in every subclass and keeps the naming
        # consistent across the system.
        self.name = self.__class__.__name__

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """
        Execute the service logic on the provided data.

        Args:
            data:      Input dict — guaranteed to contain 'digital_replicas'.
            dr_type:   Optional filter to restrict processing to a specific DR type
                       (e.g. 'gateway', 'sensor').
            attribute: Optional filter for a specific measurement attribute
                       (e.g. 'temperature', 'air_quality').

        Returns:
            Processed result in any format (dict, list, scalar, …).
        """
        pass
    # @abstractmethod
    # def execute(self, data: Dict, dr_type: str = None, attribute: str = None) -> Any:
    #     """
    #     Execute the service logic on the provided data.

    #     Args:
    #         data:      Input dict — guaranteed to contain 'digital_replicas'.
    #         dr_type:   Optional filter to restrict processing to a specific DR type
    #                    (e.g. 'gateway', 'sensor').
    #         attribute: Optional filter for a specific measurement attribute
    #                    (e.g. 'temperature', 'air_quality').

    #     Returns:
    #         Processed result in any format (dict, list, scalar, …).
    #     """
    #     pass
