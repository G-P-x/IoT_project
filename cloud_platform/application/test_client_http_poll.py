"""
Quick test module for poll_gateway behavior.
Run with: python -m cloud_platform.application.test_client_http_poll
"""

from datetime import datetime
import os
from unittest.mock import MagicMock, patch

import requests

os.environ.setdefault("FLASK_PORT", "5000")

from cloud_platform.application import client_http


def _mock_response(json_body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    return resp


def test_poll_gateway_success():
    body = [
        {
            "time_stamp": "2026-05-05T14:30:00.000Z",
            "record": {
                "id": "mpu6050_01",
                "type": "accelerometer",
                "status": "ERROR",
                "severity": "critical",
                "value": None,
                "message": "MPU-6050 connection lost",
                "timestamp": "2026-02-16T15:40:12Z",
            },
        }
    ]

    with patch("cloud_platform.application.client_http.requests.get") as mock_get:
        mock_get.return_value = _mock_response(body)
        result = client_http._poll_gateway("http://example.com")

    assert result["status"] == "success"
    assert result["code"] == 200
    assert result["body"] == body
    assert isinstance(result["req_timestamp"], str)
    datetime.fromisoformat(result["req_timestamp"])


def test_poll_gateway_error():
    with patch(
        "cloud_platform.application.client_http.requests.get",
        side_effect=requests.RequestException("boom"),
    ):
        result = client_http._poll_gateway("http://example.com")

    assert result["status"] == "error"
    assert result["code"] == client_http.CUSTOM_ERROR_CODE
    assert "boom" in result["error"]
    assert isinstance(result["req_timestamp"], str)
    datetime.fromisoformat(result["req_timestamp"])


def main() -> None:
    test_poll_gateway_success()
    test_poll_gateway_error()
    print("poll_gateway tests: OK")


if __name__ == "__main__":
    main()
