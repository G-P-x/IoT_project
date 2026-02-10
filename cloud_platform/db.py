from dataclasses import dataclass
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection


@dataclass(frozen=True)
class Collections:
    telemetry: Collection
    health: Collection
    commands: Collection
    anomalies: Collection


class MongoDB:
    """
    DB layer for a single Digital Twin.
        - Uses MongoDB as the underlying database.
        - Implements singleton pattern to ensure only one instance of MongoDB client is created and shared across the app.
    Business logic stays in dt_service.py.
    """
    _instance: "MongoDB" | None = None # _instance could be a singleton instance of MongoDB, eventually initialized with none.

    def __new__(cls, mongo_uri: str, db_name: str) -> "MongoDB":
        if not cls._instance:
            cls._instance = super(MongoDB, cls).__new__(cls)
            cls._instance._initialize(mongo_uri, db_name)
        return cls._instance
    
    def _initialize(self, mongo_uri: str, db_name: str) -> None:
        self._client = MongoClient(mongo_uri)
        self._db = self._client[db_name]

        self.collections = Collections(
            telemetry=self._db["telemetry"],
            health=self._db["health"],
            commands=self._db["commands"],
            anomalies=self._db["anomalies"],
        )
        self._ensure_indexes()


    def _ensure_indexes(self) -> None:
        '''
        Ensure indexes for all collections.
        
        :param self: The MongoDB instance
        '''
        # Telemetry query by parameter(temperature, air quality, seismic waves) + time
        self.collections.telemetry.create_index(
            [("parameter", ASCENDING), ("t_acq", ASCENDING)]
        )
        # Telemetry query by sensor_id + time
        self.collections.telemetry.create_index(
            [("sensor_id", ASCENDING), ("t_acq", ASCENDING)]
        )

        # Health query by twin_id + sensor_id + time
        self.collections.health.create_index(
            [("sensor_id", ASCENDING), ("t_event", ASCENDING)]
        )
        # Commands query by command_id
        self.collections.commands.create_index([("command_id", ASCENDING)], unique=True)
        # Anomalies by detected time
        self.collections.anomalies.create_index([("t_detected", ASCENDING)])

    def close(self) -> None:
        self._client.close()

    def get_db(self):
        return self._db
    
    def get_client(self):
        return self._client
