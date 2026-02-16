import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from config.config import Config

# payload format:
# {
#     "sensors": ["t1", "aq1", "s1"],  # optional, if not provided, assume all sensors for the parameter
#     "command": "cmd_01",
# }

TEMPERATURE = 1
SIESMIC_WAVES = 2
AIR_QUALITY = 3

logger = logging.getLogger(__name__)
cfg = Config()


def _build_url(base_url):
    """Build the notify endpoint URL for a given device base URL."""
    return base_url.rstrip("/") + "/notify"


def send_http_command(device_url, command, sensors=None):
    """
    Send an HTTP POST to a single edge device.

    Args:
        device_url: Base URL of the edge device (e.g. "http://192.168.1.10:5000").
        command:    The command string (e.g. "cmd_01").
        sensors:    Optional list of sensor ids.
    Returns:
        A requests.Response on success, or None on failure.
    """
    url = _build_url(device_url)
    payload = {"command": command}
    if sensors is not None:
        payload["sensors"] = sensors

    try:
        response = requests.post(url, json=payload, timeout=10)
        logger.info("HTTP notify → %s  response: %s – %s", url, response.status_code, response.text)
        return response
    except requests.RequestException as e:
        logger.error("HTTP notify → %s  failed: %s", url, e)
        return None


def send_command_to_all_devices(command, sensors=None, device_ids=None):
    """
    Fan-out a command to multiple edge devices in parallel.

    Uses a ThreadPoolExecutor so that every device request runs concurrently.
    The calling Flask thread blocks until ALL workers finish, but other Flask
    request threads keep running normally.

    Args:
        command:    The command string (e.g. "cmd_01").
        sensors:    Optional list of sensor ids.
        device_ids: Optional list of device IDs to target.
                    If None, the command is sent to ALL configured devices.
    Returns:
        A dict mapping device_id → result dict, where each result contains:
            - "status":  "success" | "error"
            - "code":    HTTP status code (if success)
            - "body":    Response body (if success)
            - "error":   Error description (if error)
    """
    devices = cfg.EDGE_DEVICES  # {device_id: base_url, …}

    # Filter to specific devices if requested
    if device_ids is not None:
        devices = {did: url for did, url in devices.items() if did in device_ids}

    results = {}

    with ThreadPoolExecutor(max_workers=len(devices) or 1) as executor:
        # Submit one task per device
        future_to_device = {
            executor.submit(send_http_command, url, command, sensors): device_id
            for device_id, url in devices.items()
        }

        # Collect results as they complete
        for future in as_completed(future_to_device):
            device_id = future_to_device[future]
            try:
                response = future.result()
                if response is not None:
                    content_type = response.headers.get("content-type", "")
                    results[device_id] = {
                        "status": "success",
                        "code": response.status_code,
                        "body": response.json() if "application/json" in content_type else response.text,
                    }
                else:
                    results[device_id] = {
                        "status": "error",
                        "error": "No response from device.",
                    }
            except Exception as e:
                results[device_id] = {
                    "status": "error",
                    "error": str(e),
                }