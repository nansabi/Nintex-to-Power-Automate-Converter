"""JSON Generator for simplified Power Automate flow definitions.

Constructs the final dictionary and JSON string from a ConversionResult.
Optionally appends advisory llm_suggestions when use_llm was enabled.
Note: The generated output represents a simplified subset of the Power Automate
schema designed for portfolio migration demonstrations.
Always verify action schemas against official Microsoft documentation.
"""

from __future__ import annotations

import json
from typing import Any

from src.mapper import ConversionResult


def generate_flow_dict(result: ConversionResult) -> dict[str, Any]:
    """Build a simplified Power Automate flow definition dictionary.

    Args:
        result: The ConversionResult produced by map_workflow.

    Returns:
        A dictionary following the simplified Power Automate flow schema:
          - name: Flow title
          - definition: triggers and actions linked via runAfter
          - needs_manual_review: True if any unsupported actions exist
          - unsupported: List of unsupported action details
          - warnings: List of expression conversion warnings
          - metrics: Conversion metrics summary
          - llm_suggestions: List of advisory AI suggestions (included if use_llm=True)
    """
    # If any unsupported actions were encountered, flag for manual inspection
    needs_manual_review = len(result.unsupported) > 0

    flow_dict: dict[str, Any] = {
        "name": result.flow_name,
        "definition": {
            # Verify against Microsoft docs: flow definition triggers schema
            "triggers": result.trigger,
            # Verify against Microsoft docs: flow definition actions schema
            "actions": result.converted_actions,
        },
        "needs_manual_review": needs_manual_review,
        "unsupported": [item.model_dump() for item in result.unsupported],
        "warnings": result.warnings,
        "metrics": {
            "total_actions": result.total_actions,
            "converted_count": result.converted_count,
            "coverage_percent": result.coverage_percent,
        },
    }

    # Only include llm_suggestions if use_llm mode was active
    if result.use_llm:
        flow_dict["llm_suggestions"] = [
            item.model_dump() for item in result.llm_suggestions
        ]

    return flow_dict


def generate_flow_json(result: ConversionResult, indent: int = 2) -> str:
    """Serialize the generated flow dictionary into a formatted JSON string.

    Args:
        result: The ConversionResult produced by map_workflow.
        indent: Indentation level for pretty-printing JSON.

    Returns:
        A formatted JSON string representing the flow definition.
    """
    flow_dict = generate_flow_dict(result)
    return json.dumps(flow_dict, indent=indent, ensure_ascii=False)
