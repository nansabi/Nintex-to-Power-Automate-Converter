"""Tests for shared service layer functions in src.service."""

from __future__ import annotations

from pathlib import Path
import pytest

from src.service import convert_workflow_xml, list_supported_actions, validate_workflow_xml


def test_service_convert_01_leave_approval_ok() -> None:
    """Sample 01 should convert cleanly with 100% coverage and success=True."""
    sample_path = Path("samples/01_leave_approval.xml")
    xml_content = sample_path.read_text(encoding="utf-8")

    result = convert_workflow_xml(xml_content, use_llm=False)
    assert result["success"] is True
    assert result["name"] == "Leave Request Approval"
    assert result["metrics"]["coverage_percent"] == 100.0
    assert result["needs_manual_review"] is False
    assert result["report"]["manual_review_status"] == "No"
    assert len(result["unsupported"]) == 0


def test_service_convert_unsupported_loop_flagged() -> None:
    """Sample 04 contains an unsupported Loop action and must be flagged for review."""
    sample_path = Path("samples/04_unsupported_loop.xml")
    xml_content = sample_path.read_text(encoding="utf-8")

    result = convert_workflow_xml(xml_content, use_llm=False)
    assert result["success"] is True
    assert result["needs_manual_review"] is True
    assert len(result["unsupported"]) == 1
    assert result["unsupported"][0]["original_type"] == "Loop"
    assert result["report"]["manual_review_status"] == "YES (Action required)"


def test_service_rejects_oversize_input() -> None:
    """Payloads exceeding 200 KB must be cleanly rejected with a clear error."""
    huge_xml = "<Workflow name='Big'>" + ("<!-- comment -->" * 15000) + "</Workflow>"
    assert len(huge_xml.encode("utf-8")) > 200 * 1024

    result = convert_workflow_xml(huge_xml)
    assert result["success"] is False
    assert "200 KB" in result["error"]

    val_result = validate_workflow_xml(huge_xml)
    assert val_result["valid"] is False
    assert "200 KB" in val_result["error"]


def test_service_rejects_doctype_and_entity_injection() -> None:
    """XML with DOCTYPE or ENTITY definitions must be rejected for XXE defense."""
    xxe_xml = """<?xml version="1.0"?>
    <!DOCTYPE foo [ <!ELEMENT foo ANY >
    <!ENTITY xxe SYSTEM "file:///etc/passwd" >]>
    <Workflow name="Attack">&xxe;</Workflow>"""

    result = convert_workflow_xml(xxe_xml)
    assert result["success"] is False
    assert "DOCTYPE" in result["error"] or "ENTITY" in result["error"]

    val_result = validate_workflow_xml(xxe_xml)
    assert val_result["valid"] is False
    assert "DOCTYPE" in val_result["error"] or "ENTITY" in val_result["error"]


def test_service_malformed_xml_clean_error() -> None:
    """Malformed XML must return a clean error without crashing or stack traces."""
    broken_xml = "<Workflow name='Broken'><Actions><UnclosedTag></Actions></Workflow>"

    result = convert_workflow_xml(broken_xml)
    assert result["success"] is False
    assert "parse error" in result["error"].lower() or "malformed" in result["error"].lower()

    val_result = validate_workflow_xml(broken_xml)
    assert val_result["valid"] is False
    assert "parse error" in val_result["error"].lower() or "malformed" in val_result["error"].lower()


def test_service_validate_workflow_xml_ok() -> None:
    """Valid workflow should report action count, types, and variables."""
    sample_path = Path("samples/01_leave_approval.xml")
    xml_content = sample_path.read_text(encoding="utf-8")

    val_result = validate_workflow_xml(xml_content)
    assert val_result["valid"] is True
    assert val_result["workflow_name"] == "Leave Request Approval"
    assert val_result["action_count"] == 5
    assert "SendEmail" in val_result["action_types"]
    assert "RequestApproval" in val_result["action_types"]
    assert val_result["variables_count"] == 3


def test_service_list_supported_actions() -> None:
    """list_supported_actions should return supported and unsupported metadata."""
    info = list_supported_actions()
    supported_types = [a["nintex_type"] for a in info["supported_actions"]]
    assert "Start" in supported_types
    assert "SendEmail" in supported_types
    assert "RequestApproval" in supported_types
    assert "Condition" in supported_types
    assert "SetVariable" in supported_types

    unsupported_types = [a["nintex_type"] for a in info["unsupported_actions"]]
    assert "Loop" in unsupported_types
    assert "WebServiceCall" in unsupported_types
