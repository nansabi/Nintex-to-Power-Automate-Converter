"""Model Context Protocol (MCP) server for Nintex to Power Automate conversion.

Exposes tools via FastMCP over standard I/O (stdio transport) for LLM agents
to inspect, validate, and convert Nintex XML workflows into Power Automate flows.
"""

from __future__ import annotations

import json
from typing import Any
from mcp.server.fastmcp import FastMCP

from src.service import (
    convert_workflow_xml,
    list_supported_actions as svc_list_supported_actions,
    validate_workflow_xml,
)

# Initialize FastMCP server instance
mcp = FastMCP("nintex-to-power-automate")


@mcp.tool(
    name="convert_workflow",
    description=(
        "Convert a legacy Nintex workflow XML string to a Power Automate flow definition. "
        "Returns the converted flow JSON structure and summary metrics. "
        "Optionally enables AI suggestions for unsupported actions if use_llm is true."
    ),
)
def convert_workflow(workflow_xml: str, use_llm: bool = False) -> str:
    """Convert a Nintex workflow XML string into a Power Automate flow definition.

    Args:
        workflow_xml: Raw XML string of the Nintex workflow definition.
        use_llm: If true, query the LLM to suggest translations for unsupported actions.

    Returns:
        JSON string representing the conversion result dictionary.
    """
    result = convert_workflow_xml(workflow_xml, use_llm=use_llm)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="validate_workflow",
    description=(
        "Validate a Nintex workflow XML string without converting it. "
        "Returns workflow name, total action count, list of distinct action types, "
        "and variables count, or an error message if invalid."
    ),
)
def validate_workflow(workflow_xml: str) -> str:
    """Validate Nintex XML workflow structure and list contained action types.

    Args:
        workflow_xml: Raw XML string of the Nintex workflow.

    Returns:
        JSON string containing validation status, workflow metadata, and action types.
    """
    result = validate_workflow_xml(workflow_xml)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="list_supported_actions",
    description=(
        "List all Nintex action types supported by the converter and their corresponding "
        "Power Automate action and connector targets, along with unsupported action strategies."
    ),
)
def list_supported_actions() -> str:
    """Return the registry of supported and unsupported actions.

    Returns:
        JSON string detailing supported action mappings and unsupported handling strategies.
    """
    result = svc_list_supported_actions()
    return json.dumps(result, indent=2)


def main() -> None:
    """Start the FastMCP server over standard I/O (stdio transport)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
