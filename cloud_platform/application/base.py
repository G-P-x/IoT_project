"""
Base Application Module
========================
Abstract base class for application-layer components.

Architecture reasoning (from the lecture):
- The application layer sits on top of the DT core and services. It exposes
  domain functionality to external consumers (REST APIs, CLI, dashboards, …).
- Having a base class enforces a uniform interface (process_data) and makes it
  easy to add new application modules (e.g. a CLI tool, a scheduled job).
"""

from abc import ABC, abstractmethod
from typing import Dict


class BaseApplication(ABC):
    """
    Abstract base class for all application-level components.

    Subclasses should implement process_data() with their domain-specific logic.
    """

    def __init__(self):
        self.name = self.__class__.__name__

    @abstractmethod
    def process_data(self, data: Dict) -> Dict:
        """
        Process input data and return results.

        Args:
            data: Input data in any format.

        Returns:
            A dict containing the processed results.
        """
        pass
