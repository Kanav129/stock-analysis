"""Tests for Qwen / DashScope status service."""
from unittest.mock import patch

from services.qwen_service import QwenService, _extract_balance


def test_extract_balance_from_available_balance():
    body = {"data": {"available_balance": "12.50"}}
    assert _extract_balance(body) == 12.5


def test_extract_balance_missing():
    assert _extract_balance({"data": {}}) is None


@patch("services.qwen_service.requests.get")
def test_get_status_no_key(mock_get):
    status = QwenService(api_key="").get_status()
    assert status["connected"] is False
    assert status["provider"] == "qwen"
    mock_get.assert_not_called()


@patch("services.qwen_service.requests.get")
def test_get_status_connected(mock_get):
    def side_effect(url, **kwargs):
        class Resp:
            status_code = 200

            @staticmethod
            def json():
                if url.endswith("/models"):
                    return {"data": [{"id": "qwen3.7-flash"}, {"id": "qwen3.7-max"}]}
                return {"data": {"available_balance": "25.00"}}

        return Resp()

    mock_get.side_effect = side_effect
    status = QwenService(api_key="sk-test").get_status()
    assert status["connected"] is True
    assert status["key"]["models_available"] == 2
    assert status["credits"]["remaining"] == 25.0
