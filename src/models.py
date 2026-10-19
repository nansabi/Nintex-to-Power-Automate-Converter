"""Domain models for workflow representation.

This module defines the typed Pydantic models used to represent a parsed
workflow. It includes models for workflows, actions, variables, and an
enumeration of supported action types.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Supported workflow action types.

    If an action type from XML is not among the supported types, it will be
    mapped to UNKNOWN rather than failing or guessing.
    """

    START = "Start"
    SEND_EMAIL = "SendEmail"
    REQUEST_APPROVAL = "RequestApproval"
    CONDITION = "Condition"
    SET_VARIABLE = "SetVariable"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, raw_type: str) -> ActionType:
        """Safely convert a string to an ActionType enum member.

        If the string matches a known action type (case-insensitive), that
        member is returned. Otherwise, ActionType.UNKNOWN is returned.

        Args:
            raw_type: The raw string type from the workflow XML.

        Returns:
            The corresponding ActionType member, or ActionType.UNKNOWN.
        """
        cleaned = raw_type.strip().lower()
        for member in cls:
            if member.value.lower() == cleaned:
                return member
        return cls.UNKNOWN


class Variable(BaseModel):
    """Represents a declared variable in the workflow.

    Variables can store workflow state, default values, or runtime values,
    and can be referenced inside action settings (e.g. {Variable:Name}).

    Attributes:
        name: The name or identifier of the variable.
        value: The initial/default value stored in the variable.
    """

    name: str
    value: str = ""


class Action(BaseModel):
    """Represents a single step or task inside a workflow.

    For conditional actions (type == ActionType.CONDITION), then_actions
    and else_actions hold the nested actions for each respective branch.

    Attributes:
        id: Unique identifier for the action (e.g. 'act-1').
        type: The category of action (Start, SendEmail, Condition, etc.).
        name: Human-readable display name for the action.
        settings: Key-value dictionary containing action-specific configurations.
        then_actions: List of actions to execute if condition is True.
        else_actions: List of actions to execute if condition is False.
    """

    id: str
    type: ActionType
    name: str
    settings: dict[str, Any] = Field(default_factory=dict)
    then_actions: list[Action] = Field(default_factory=list)
    else_actions: list[Action] = Field(default_factory=list)
    original_type: str | None = None
    raw_xml: str | None = None


class Workflow(BaseModel):
    """Represents the complete parsed workflow definition.

    Attributes:
        name: The title or name of the workflow.
        variables: List of declared workflow variables.
        actions: Sequence of top-level actions in the workflow.
    """

    name: str
    variables: list[Variable] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)


# Pydantic v2 requires rebuilding models that have recursive self-references
# (Action has then_actions: list[Action] and else_actions: list[Action]).
Action.model_rebuild()
