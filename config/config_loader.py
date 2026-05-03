import yaml
from typing import Dict
import os


class ConfigLoader:
    """
    Utility class for loading YAML configuration files.

    Provides both a generic load_config() method and database-specific helpers
    (load_database_config, build_connection_string) following the same pattern
    as the lecture's ConfigLoader.
    """

    @staticmethod
    def load_config(config_path: str) -> Dict:
        """
        Load configuration from a YAML file.

        Args:
            config_path (str): Path to the YAML configuration file.

        Returns:
            Dict: Configuration data loaded from the YAML file.
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as file:
            config = yaml.safe_load(file)

        return config

    # ── Database-specific helpers (mirroring the lecture) ─────────────

    @staticmethod
    def load_database_config(config_path: str = "config/database.yaml") -> Dict:
        """
        Load and validate the database configuration from a YAML file.

        Expects a top-level 'database' key containing 'connection' and 'settings'.

        Returns:
            The 'database' sub-dict from the YAML.

        Raises:
            FileNotFoundError: If the config file does not exist.
            ValueError:        If the YAML is missing the 'database' section.
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        if not config or "database" not in config:
            raise ValueError("Invalid configuration file: missing 'database' section")

        return config["database"]

    @staticmethod
    def build_connection_string(config: Dict) -> str:
        """
        Build a MongoDB connection string from the database config dict.

        Supports optional username/password authentication. If both are empty
        the connection string omits the auth@ prefix.

        Args:
            config: The 'database' sub-dict (must contain a 'connection' key).

        Returns:
            A mongodb:// connection string.
        """
        conn = config["connection"]
        host = conn["host"]
        port = conn["port"]

        # Build the optional authentication prefix
        auth = ""
        if conn.get("username") and conn.get("password"):
            auth = f"{conn['username']}:{conn['password']}@"

        return f"mongodb://{auth}{host}:{port}"