"""Tests for MCP server tool registration and execution in src.mcp_server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from src.mcp_server import mcp, convert_workflow, list_supported_actions, validate_workflow
from src.service import convert_workflow_xml, list_supported_actions as svc_list_supported_actions, validate_workflow_xml


def test_mcp_tools_are_registered_with_expected_names() -> None:
    """The FastMCP server must expose convert_workflow, validate_workflow, list_supported_actions."""
    tools = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools]

    assert "convert_workflow" in tool_names
    assert "validate_workflow" in tool_names
    assert "list_supported_actions" in tool_names


def test_mcp_convert_workflow_tool_matches_service() -> None:
    """Calling convert_workflow tool returns identical data to service.py."""
    sample_xml = Path("samples/01_leave_approval.xml").read_text(encoding="utf-8")

    tool_result_json = convert_workflow(workflow_xml=sample_xml, use_llm=False)
    tool_result = json.loads(tool_result_json)

    service_result = convert_workflow_xml(sample_xml, use_llm=False)

    assert tool_result["name"] == service_result["name"]
    assert tool_result["metrics"] == service_result["metrics"]
    assert tool_result["success"] == service_result["success"]
    assert tool_result["needs_manual_review"] == service_result["needs_manual_review"]


def test_mcp_validate_workflow_tool_matches_service() -> None:
    """Calling validate_workflow tool returns identical data to service.py."""
    sample_xml = Path("samples/01_leave_approval.xml").read_text(encoding="utf-8")

    tool_result_json = validate_workflow(workflow_xml=sample_xml)
    tool_result = json.loads(tool_result_json)

    service_result = validate_workflow_xml(sample_xml)

    assert tool_result == service_result


def test_mcp_list_supported_actions_tool_matches_service() -> None:
    """Calling list_supported_actions tool returns identical data to service.py."""
    tool_result_json = list_supported_actions()
    tool_result = json.loads(tool_result_json)

    service_result = svc_list_supported_actions()

    assert tool_result == service_result
