"""Shared workflow conversion and validation service layer.

Provides plain Python functions for converting, validating, and inspecting
Nintex XML workflows, used by both the MCP server and the REST API.
"""

from __future__ import annotations

import os
from typing import Any
import xml.etree.ElementTree as ET

from src.generator import generate_flow_dict
from src.mapper import map_workflow
from src.models import ActionType
from src.parser import WorkflowParseError, parse_workflow_from_string

# Maximum allowed XML payload size: 200 KB (204,800 bytes)
MAX_XML_SIZE_BYTES = 200 * 1024


def _check_and_sanitize_xml(xml_text: str) -> None:
    """Validate XML input for size limits, type safety, and XXE / entity injections.

    Args:
        xml_text: Raw XML input string.

    Raises:
        ValueError: If input is not a string, exceeds 200 KB, contains DOCTYPE/ENTITY,
                    or is empty.
    """
    if not isinstance(xml_text, str):
        raise ValueError("Invalid input: XML payload must be a string.")

    encoded = xml_text.encode("utf-8")
    if len(encoded) > MAX_XML_SIZE_BYTES:
        raise ValueError(
            f"XML payload exceeds maximum permitted size of 200 KB ({len(encoded)} bytes received)."
        )

    # Refuse DOCTYPE or ENTITY declarations to protect against XXE and entity expansion (Billion Laughs)
    upper_xml = xml_text.upper()
    if "<!DOCTYPE" in upper_xml or "<!ENTITY" in upper_xml:
        raise ValueError(
            "Security violation: DOCTYPE and ENTITY declarations are strictly forbidden."
        )


def convert_workflow_xml(xml_text: str, use_llm: bool = False) -> dict[str, Any]:
    """Convert a Nintex workflow XML string to a Power Automate flow dictionary.

    Args:
        xml_text: The Nintex XML workflow content as a string.
        use_llm: If True, invoke LLM suggestion pipeline for unsupported actions
                 (only succeeds if GROQ_API_KEY is present in the environment).

    Returns:
        A dictionary containing:
          - flow: The complete Power Automate flow definition (matching CLI JSON output)
          - report: High-level summary metrics and review flags
          - success: True
        Or if an error occurs, returns a clean error dictionary without stack traces.
    """
    try:
        _check_and_sanitize_xml(xml_text)
    except ValueError as err:
        return {"success": False, "error": str(err)}

    # Ensure use_llm=True only functions when GROQ_API_KEY is present in the environment
    effective_use_llm = False
    if use_llm:
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key and groq_key.strip():
            effective_use_llm = True
        else:
            effective_use_llm = False

    try:
        workflow = parse_workflow_from_string(xml_text, source_name="<service_input>")
        result = map_workflow(workflow, use_llm=effective_use_llm)
        flow_dict = generate_flow_dict(result)

        review_status = "YES (Action required)" if result.unsupported else "No"
        report = {
            "flow_name": result.flow_name,
            "total_actions": result.total_actions,
            "converted_count": result.converted_count,
            "coverage_percent": result.coverage_percent,
            "needs_manual_review": bool(result.unsupported),
            "manual_review_status": review_status,
            "unsupported_count": len(result.unsupported),
            "warnings_count": len(result.warnings),
            "llm_suggestions_count": len(result.llm_suggestions),
        }

        # Merge flow dict fields at top-level alongside explicit report metadata
        output = dict(flow_dict)
        output["report"] = report
        output["success"] = True
        return output

    except WorkflowParseError as err:
        return {"success": False, "error": f"Workflow parse error: {err}"}
    except Exception as err:
        return {"success": False, "error": f"Conversion error: {err}"}


def validate_workflow_xml(xml_text: str) -> dict[str, Any]:
    """Parse and validate Nintex XML without full conversion to Power Automate.

    Args:
        xml_text: Raw Nintex workflow XML string.

    Returns:
        A dictionary with validation details:
          - valid: True/False
          - workflow_name: Extracted name (if valid)
          - action_count: Total action count
          - action_types: Distinct action types found
          - variables_count: Count of defined variables
          - error: Error message string if invalid
    """
    try:
        _check_and_sanitize_xml(xml_text)
        workflow = parse_workflow_from_string(xml_text, source_name="<validate_input>")

        def _collect_types(actions: list[Any]) -> list[str]:
            types: list[str] = []
            for act in actions:
                types.append(act.original_type or act.type.value)
                types.extend(_collect_types(act.then_actions))
                types.extend(_collect_types(act.else_actions))
            return types

        all_types = _collect_types(workflow.actions)
        distinct_types = sorted(list(set(all_types)))

        return {
            "valid": True,
            "workflow_name": workflow.name,
            "action_count": len(all_types),
            "action_types": distinct_types,
            "variables_count": len(workflow.variables),
            "error": None,
        }
    except (ValueError, WorkflowParseError) as err:
        return {
            "valid": False,
            "workflow_name": None,
            "action_count": 0,
            "action_types": [],
            "variables_count": 0,
            "error": str(err),
        }
    except Exception as err:
        return {
            "valid": False,
            "workflow_name": None,
            "action_count": 0,
            "action_types": [],
            "variables_count": 0,
            "error": f"Validation error: {err}",
        }


def list_supported_actions() -> dict[str, Any]:
    """List supported Nintex actions and their Power Automate targets, plus unsupported actions.

    Returns:
        A structured dictionary of supported mappings and unsupported fallback descriptions.
    """
    return {
        "supported_actions": [
            {
                "nintex_type": "Start",
                "power_automate_target": "Manual (Request) Trigger",
                "connector_or_type": "Request / Button",
                "notes": "Workflow entrypoint converted to manual button trigger.",
            },
            {
                "nintex_type": "SendEmail",
                "power_automate_target": "Send an email (V2)",
                "connector_or_type": "OpenApiConnection (Office 365 Outlook)",
                "notes": "Maps recipient (to), subject, and HTML body.",
            },
            {
                "nintex_type": "RequestApproval",
                "power_automate_target": "Start and wait for an approval",
                "connector_or_type": "OpenApiConnection (Approvals)",
                "notes": "Maps approver, task title, and first-to-respond type.",
            },
            {
                "nintex_type": "Condition",
                "power_automate_target": "Condition (If)",
                "connector_or_type": "If Control",
                "notes": "Branches into Then ('actions') and Else ('else.actions').",
            },
            {
                "nintex_type": "SetVariable",
                "power_automate_target": "Set variable",
                "connector_or_type": "SetVariable Control",
                "notes": "Updates declared variable values.",
            },
            {
                "nintex_type": "Workflow Variables",
                "power_automate_target": "Initialize variable",
                "connector_or_type": "InitializeVariable Control",
                "notes": "Automatically initialized at start of flow for each declared variable.",
            },
        ],
        "unsupported_actions": [
            {
                "nintex_type": "Loop",
                "strategy": "Flagged for manual review (LLM suggests Until or Foreach with condition inversion).",
            },
            {
                "nintex_type": "WebServiceCall",
                "strategy": "Flagged for manual review (LLM suggests Http action).",
            },
            {
                "nintex_type": "Parallel Branches",
                "strategy": "Flagged for manual review; parallel branches deferred.",
            },
            {
                "nintex_type": "Custom Code / Script",
                "strategy": "Flagged for manual review; custom script deferred.",
            },
        ],
    }
