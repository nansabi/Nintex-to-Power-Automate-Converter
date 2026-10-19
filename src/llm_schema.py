"""Pydantic schemas for LLM structured output.

Defines the contract for LLM-based action suggestions when rule-based
mapping encounters unsupported Nintex action types.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class LLMSuggestion(BaseModel):
    """Schema for structured suggestions produced by the LLM for unsupported actions.

    Attributes:
        suggested_action_type: Recommended Power Automate action or connector type.
        power_automate_action: Proposed Power Automate action definition dictionary.
        confidence: Confidence score strictly bounded between 0.0 and 1.0.
        reasoning: Justification or explanation of the suggested mapping.
        needs_human_review: Always True for AI-generated suggestions.
    """

    suggested_action_type: str = Field(
        ...,
        description="Name of the suggested Power Automate action or control block.",
    )
    power_automate_action: dict[str, Any] = Field(
        ...,
        description="Dictionary representing the Power Automate action definition.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0.",
    )
    reasoning: str = Field(
        ...,
        description="Explanation of why this action was suggested.",
    )
    needs_human_review: bool = Field(
        default=True,
        description="Whether this suggestion requires human review (always True for AI outputs).",
    )

    @field_validator("power_automate_action")
    @classmethod
    def validate_action_non_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Ensure power_automate_action is not an empty dictionary."""
        if not value:
            raise ValueError("power_automate_action dictionary must not be empty.")
        return value


class ActionSuggestionItem(BaseModel):
    """Container associating a workflow action with its LLM suggestion.

    Attributes:
        action_id: ID of the unsupported Nintex action.
        action_name: Display name of the action.
        original_type: Original Nintex type string (e.g. 'Loop').
        suggestion: Validated LLMSuggestion payload.
        confidence: Echoed confidence score for quick reference.
    """

    action_id: str
    action_name: str
    original_type: str
    suggestion: LLMSuggestion
    confidence: float
