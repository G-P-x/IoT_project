from cloud_platform.services.database_service import DatabaseService # used just to check the input
from typing import Dict, Optional

def find_dr(db_service: DatabaseService, device_id: str) -> Optional[Dict]:
    """
    Look up the DR by the physical device_id.

    Returns:
        The DR document dict or None if not found.
    """
    # Try to find an existing DR by device_id in the device collection
    #if the device_id is not found, return None
    existing = db_service.query_drs("device", {"profile.device_id": device_id})
    if existing: # if the list is not empty, return the first match (there should be only one)
        return existing[0]
    return None

def find_dt(db_service: DatabaseService, device_id: str) -> Optional[Dict]:
    """
    Look up the DT by the physical device_id.

    Returns:
        The DT document dict or None if not found.
    """
    # Try to find an existing DT by device_id in the digital_twin collection
    #if the device_id is not found, return None
    existing = db_service.query_drs("digital_twin", {"profile.device_id": device_id})
    if existing: # if the list is not empty, return the first match (there should be only one)
        return existing[0]
    return None