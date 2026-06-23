import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from config.config import Config
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
cfg    = Config()

CUSTOM_ERROR_CODE = 104  # usato quando la request fallisce senza response object


def send_alarm():
    pass


def _send_http_command(url, command, field_devices):
    """
    Invia un POST /command a un singolo gateway edge.

    Args:
        url:           URL base del gateway (es. "http://10.98.201.225:8080").
        command:       Stringa comando (es. "cmd_01").
        field_devices: Lista di device ID da interrogare; lista vuota = tutti.

    Returns:
        Dict con status/code/body oppure status/code/error.
    """
    endpoint = url.rstrip("/") + cfg.COMMAND_ENDPOINT
    payload  = {"command": command, "sensors": field_devices}

    try:
        print(f"Sending command to {endpoint} with payload: {payload}")
        response = requests.post(endpoint, json=payload, timeout=10)
        response.raise_for_status()
        body = response.json()
        logger.info("HTTP notify → %s  %s", endpoint, response.status_code)
        return {
            "status": "success",
            "code": response.status_code,
            "req_timestamp": datetime.now(timezone.utc).isoformat(),
            "body": body,
        }
    except requests.RequestException as e:
        logger.error("HTTP notify → %s  failed: %s", endpoint, e)
        return {
            "status": "error",
            "code": CUSTOM_ERROR_CODE,
            "error": str(e),
            "req_timestamp": datetime.now(timezone.utc).isoformat(),
        }


def send_command_to_sensors(command, target: dict):
    """
    Fan-out parallelo di un comando verso più gateway.

    Args:
        command: Stringa comando.
        target:  Dict gateway_id → lista field device ID.

    Returns:
        Dict gateway_id → risultato normalizzato.
    """
    gateway_ids  = list(target.keys()) if isinstance(target, dict) else list(cfg.EDGE_DEVICES.keys())
    field_devices = list(target.values()) if isinstance(target, dict) else [[] for _ in gateway_ids]
    urls = [cfg.EDGE_DEVICES[gid] for gid in gateway_ids]

    assert len(urls) > 0, "No devices to send command to."
    assert len(urls) == len(field_devices) == len(gateway_ids)

    results = {}
    with ThreadPoolExecutor(max_workers=len(gateway_ids) or 1) as executor:
        future_to_device = {
            executor.submit(_send_http_command, urls[i], command, field_devices[i]): gateway_ids[i]
            for i in range(len(gateway_ids))
        }
        for future in as_completed(future_to_device):
            gateway_id = future_to_device[future]
            try:
                results[gateway_id] = _normalize_result(future.result())
            except Exception as e:
                print(f"Error sending command to gateway {gateway_id}: {e}")
                results[gateway_id] = _normalize_result({
                    "status": "error",
                    "code": CUSTOM_ERROR_CODE,
                    "error": str(e),
                    "req_timestamp": datetime.now(timezone.utc).isoformat(),
                })
    return results


def _normalize_result(result):
    """
    Normalizza la risposta grezza di un gateway nel formato interno:
    {
        "gateway_info": { status, code, error, req_timestamp },
        "records": {
            record_id: { type, status, severity, value, message, timestamp, threshold }
        }
    }
    """
    if not isinstance(result, dict) or "status" not in result:
        raise ValueError("Invalid result format: expected a dict with a 'status' key")

    def _normalize_records(body):
        """
        Estrae i record dal body della risposta gateway.

        Il gateway restituisce una lista di oggetti {time_stamp, record}
        dove ogni record contiene ora anche il campo 'threshold' embedded.
        """
        if isinstance(body, list):
            records = {}
            for json_item in body:
                if not isinstance(json_item, dict) or "record" not in json_item:
                    continue
                rec = json_item.get("record", {})
                records[rec.get("id")] = {
                    "type":      rec.get("type", "sensor"),
                    "status":    rec.get("status"),
                    "severity":  rec.get("severity"),
                    "value":     rec.get("value"),
                    "message":   rec.get("message"),
                    "timestamp": rec.get("timestamp"),
                    "threshold": rec.get("threshold"),  # soglia critica embedded
                }
            return records

        if isinstance(body, dict) and isinstance(body.get("body"), (list, dict)):
            return _normalize_records(body.get("body"))

        if isinstance(body, dict) and isinstance(body.get("records"), list):
            records = {}
            for rec in body.get("records", []):
                if not isinstance(rec, dict):
                    continue
                records[rec.get("id")] = {
                    "type":      rec.get("type", "sensor"),
                    "status":    rec.get("status"),
                    "severity":  rec.get("severity"),
                    "value":     rec.get("value"),
                    "message":   rec.get("message"),
                    "timestamp": rec.get("timestamp"),
                    "threshold": rec.get("threshold"),
                }
            return records

        return {}

    return {
        "gateway_info": {
            "status":        result.get("status"),
            "code":          result.get("code"),
            "error":         result.get("error") if result.get("status") == "error" else None,
            "req_timestamp": result.get("req_timestamp"),
        },
        "records": _normalize_records(result.get("body")) if result.get("status") == "success" else {},
    }


def _poll_gateway(url) -> dict:
    """
    Interroga un singolo gateway tramite GET /data.

    Returns:
        Dict raw con status/code/body oppure status/code/error.
    """
    endpoint = url.rstrip("/") + cfg.POLL_ENDPOINT
    try:
        resp = requests.get(endpoint, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        return {
            "status": "success",
            "code": resp.status_code,
            "req_timestamp": datetime.now(timezone.utc).isoformat(),
            "body": body,
        }
    except requests.RequestException as e:
        logger.error("HTTP poll → %s failed: %s", endpoint, e)
        return {
            "status": "error",
            "code": CUSTOM_ERROR_CODE,
            "error": str(e),
            "req_timestamp": datetime.now(timezone.utc).isoformat(),
        }


def poll_gateways():
    """
    Interroga tutti i gateway configurati in parallelo.

    Returns:
        Dict gateway_id → risultato normalizzato.
    """
    results = {}
    print(f"Polling gateways: {list(cfg.EDGE_DEVICES.keys())}")

    with ThreadPoolExecutor(max_workers=len(cfg.EDGE_DEVICES) or 1) as executor:
        future_to_gateway = {
            executor.submit(_poll_gateway, url): gateway_id
            for gateway_id, url in cfg.EDGE_DEVICES.items()
        }
        for future in as_completed(future_to_gateway):
            gateway_id = future_to_gateway[future]
            try:
                result = future.result()
                results[gateway_id] = _normalize_result(result)
            except Exception as e:
                print(f"Error polling gateway {gateway_id}: {e}")
                results[gateway_id] = _normalize_result({
                    "status": "error",
                    "code": CUSTOM_ERROR_CODE,
                    "error": str(e),
                    "req_timestamp": datetime.now(timezone.utc).isoformat(),
                })

    return results