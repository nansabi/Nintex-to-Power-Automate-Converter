"""Tests for REST and webhook endpoints in src.api using FastAPI TestClient."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)


def test_api_health_endpoint() -> None:
    """GET /health must return 200 with status 'ok'."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_convert_endpoint() -> None:
    """POST /convert with sample 01 must return 200 and converted flow JSON."""
    sample_xml = Path("samples/01_leave_approval.xml").read_text(encoding="utf-8")
    payload = {"workflow_xml": sample_xml, "use_llm": False}

    response = client.post("/convert", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["name"] == "Leave Request Approval"
    assert data["metrics"]["coverage_percent"] == 100.0


def test_api_convert_invalid_xml_400() -> None:
    """POST /convert with malformed XML must return 400 Bad Request."""
    payload = {"workflow_xml": "<Malformed>test", "use_llm": False}
    response = client.post("/convert", json=payload)
    assert response.status_code == 400
    assert "parse error" in response.json()["detail"].lower() or "malformed" in response.json()["detail"].lower()


def test_api_webhook_succeeds_with_valid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /webhook/workflow-exported with valid HMAC-SHA256 signature returns 200."""
    secret = "super-secret-test-key-123"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)

    sample_xml = Path("samples/01_leave_approval.xml").read_text(encoding="utf-8")
    body_dict = {"event": "workflow.exported", "workflow_xml": sample_xml}
    raw_body = json.dumps(body_dict).encode("utf-8")

    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    response = client.post(
        "/webhook/workflow-exported",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["name"] == "Leave Request Approval"


def test_api_webhook_bad_signature_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /webhook/workflow-exported with invalid signature returns 401 Unauthorized."""
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")

    raw_body = json.dumps({"event": "workflow.exported", "workflow_xml": "<Workflow name='test' />"}).encode("utf-8")
    response = client.post(
        "/webhook/workflow-exported",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Signature": "wrong-signature-hex"},
    )
    assert response.status_code == 401
    assert "Invalid HMAC signature" in response.json()["detail"]


def test_api_webhook_missing_signature_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /webhook/workflow-exported without X-Signature header returns 401."""
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")

    raw_body = json.dumps({"event": "workflow.exported", "workflow_xml": "<Workflow name='test' />"}).encode("utf-8")
    response = client.post(
        "/webhook/workflow-exported",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401
    assert "Missing required X-Signature header" in response.json()["detail"]


def test_api_webhook_no_secret_configured_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /webhook/workflow-exported returns 503 if WEBHOOK_SECRET is not configured."""
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    raw_body = json.dumps({"event": "workflow.exported", "workflow_xml": "<Workflow name='test' />"}).encode("utf-8")
    response = client.post(
        "/webhook/workflow-exported",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Signature": "some-signature"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
