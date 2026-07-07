from dataclasses import dataclass, field
from typing import TypedDict, Any

@dataclass(order=True)
class IngestionQueueItem:
    priority: int
    # compare=False prevents Python from crashing when trying to sort dictionaries
    item: Any = field(compare=False)

@dataclass
class ServiceQueueItem:
    dt_data: Any  # list of dicts containing the digital twin data for each device
    command_id: str | None = None  # command_id of the command that generated this result




class ItemDict(TypedDict):
    service: str
    status: str
    notify: list[str] | None # e.g. ["WEBHOOK_OPERATOR", ""]
    message: str

@dataclass(order=True)
class DispatchQueueItem:
    priority: int # 0: MAX PRIORITY
    item_dict: str | ItemDict = field(compare=False)