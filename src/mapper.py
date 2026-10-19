"""Rule-based workflow mapper from Nintex models to Power Automate schema.

This module maps supported ActionType entries to Power Automate action definitions.
Optionally integrates with an LLM to propose suggestions for unsupported actions.
Note: The generated output represents a simplified subset of the Power Automate
schema designed for portfolio migration demonstrations.
Always verify action schemas against official Microsoft documentation.
"""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field

from src.expressions import convert_expression
from src.llm import suggest_conversion
from src.llm_schema import ActionSuggestionItem, LLMSuggestion
from src.models import Action, ActionType, Workflow
from src.pa_constants import (
    ACTION_TYPE_IF,
    ACTION_TYPE_INITIALIZE_VARIABLE,
    ACTION_TYPE_OPEN_API_CONNECTION,
    ACTION_TYPE_SET_VARIABLE,
    APPROVALS_API_ID,
    APPROVALS_CONNECTION_NAME,
    APPROVALS_OPERATION_ID_START_AND_WAIT,
    APPROVALS_PARAM_ASSIGNED_TO,
    APPROVALS_PARAM_TITLE,
    APPROVALS_PARAM_TYPE,
    APPROVALS_TYPE_FIRST_TO_RESPOND,
    DEFAULT_VARIABLE_TYPE,
    O365_API_ID,
    O365_CONNECTION_NAME,
    O365_OPERATION_ID_SEND_EMAIL_V2,
    O365_PARAM_BODY,
    O365_PARAM_SUBJECT,
    O365_PARAM_TO,
    OUTCOME_APPROVE,
    OUTCOME_REJECT,
    RUN_AFTER_STATUS_SUCCEEDED,
    TRIGGER_KIND_BUTTON,
    TRIGGER_NAME_MANUAL,
    TRIGGER_TYPE_REQUEST,
)


class UnsupportedAction(BaseModel):
    """Details of a workflow action that could not be mapped.

    Attributes:
        id: Unique Nintex action ID.
        name: Name of the action.
        original_type: Original action type string (e.g. 'Loop').
        reason: Explanation of why the action is unsupported.
    """

    id: str
    name: str
    original_type: str
    reason: str


class ConversionResult(BaseModel):
    """Result of mapping a Nintex workflow to Power Automate.

    Attributes:
        flow_name: Name of the converted workflow.
        trigger: The trigger definition (e.g. manual request trigger).
        converted_actions: Dictionary of mapped Power Automate actions.
        unsupported: List of unsupported actions that require manual review.
        warnings: List of warning messages generated during conversion.
        total_actions: Total number of actions present in the source workflow.
        converted_count: Number of actions successfully mapped.
        coverage_percent: Percentage of actions successfully mapped.
        use_llm: Whether LLM suggestion generation was enabled.
        llm_suggestions: List of advisory AI suggestions for unsupported actions.
    """

    flow_name: str
    trigger: dict[str, Any] = Field(default_factory=dict)
    converted_actions: dict[str, Any] = Field(default_factory=dict)
    unsupported: list[UnsupportedAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    total_actions: int = 0
    converted_count: int = 0
    coverage_percent: float = 0.0
    use_llm: bool = False
    llm_suggestions: list[ActionSuggestionItem] = Field(default_factory=list)


def _sanitize_action_name(raw_name: str, existing_names: set[str]) -> str:
    """Produce a unique, valid Power Automate action name.

    Spaces and non-alphanumeric characters are replaced with underscores.
    Duplicates are suffixed with an incremental number.

    Args:
        raw_name: Raw display name from Nintex action.
        existing_names: Set of already allocated action names in this scope.

    Returns:
        A unique, sanitized action name string.
    """
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", raw_name.strip()).strip("_")
    if not clean:
        clean = "Action"

    candidate = clean
    counter = 1
    while candidate in existing_names:
        candidate = f"{clean}_{counter}"
        counter += 1

    existing_names.add(candidate)
    return candidate


class WorkflowMapper:
    """Registry and orchestrator for mapping Nintex workflows to Power Automate."""

    def __init__(self, use_llm: bool = False, llm_client: Any = None) -> None:
        """Initialize the mapper with supported action handlers and optional LLM support.

        Args:
            use_llm: If True, invoke LLM suggestions for unsupported action types.
            llm_client: Optional injected OpenAI/Groq client for testing or custom configuration.
        """
        self._use_llm = use_llm
        self._llm_client = llm_client
        self._action_id_to_name: dict[str, str] = {}
        self._all_action_names: set[str] = set()
        self._valid_variables: set[str] = set()
        self._unsupported: list[UnsupportedAction] = []
        self._warnings: list[str] = []
        self._llm_suggestions: list[ActionSuggestionItem] = []
        self._converted_count = 0
        self._total_actions = 0

    def _pre_register_names(self, actions: list[Action]) -> None:
        """Assign sanitized Power Automate names to all supported actions.

        This ensures expression resolution can find target action names
        regardless of action ordering.

        Args:
            actions: List of actions to register.
        """
        for act in actions:
            if act.type != ActionType.UNKNOWN:
                pa_name = _sanitize_action_name(act.name, self._all_action_names)
                self._action_id_to_name[act.id] = pa_name
            # Recurse into condition branches
            self._pre_register_names(act.then_actions)
            self._pre_register_names(act.else_actions)

    def _count_actions(self, actions: list[Action]) -> int:
        """Recursively count all actions in the workflow tree.

        Args:
            actions: List of actions to count.

        Returns:
            Total count of actions including nested condition branches.
        """
        total = len(actions)
        for act in actions:
            total += self._count_actions(act.then_actions)
            total += self._count_actions(act.else_actions)
        return total

    # -------------------------------------------------------------------------
    # Action Handlers
    # -------------------------------------------------------------------------

    def _map_start(self, action: Action) -> tuple[str, dict[str, Any]] | None:
        """Map a Start action to a manual Request trigger.

        # Verify against Microsoft docs: manual trigger schema in Power Automate
        """
        self._converted_count += 1
        return None

    def _map_send_email(self, action: Action) -> tuple[str, dict[str, Any]]:
        """Map a SendEmail action to Office 365 Outlook 'Send an email (V2)'.

        # Verify against Microsoft docs: Send an email (V2) action via Office 365 Outlook
        """
        pa_name = self._action_id_to_name[action.id]
        to_raw = action.settings.get("to", "")
        subject_raw = action.settings.get("subject", "")
        body_raw = action.settings.get("body", "")

        to_converted, w1 = convert_expression(to_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        subject_converted, w2 = convert_expression(subject_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        body_converted, w3 = convert_expression(body_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        self._warnings.extend(w1 + w2 + w3)

        definition: dict[str, Any] = {
            "type": ACTION_TYPE_OPEN_API_CONNECTION,
            "inputs": {
                "host": {
                    "connectionName": O365_CONNECTION_NAME,
                    "operationId": O365_OPERATION_ID_SEND_EMAIL_V2,
                    "apiId": O365_API_ID,
                },
                "parameters": {
                    O365_PARAM_TO: to_converted,
                    O365_PARAM_SUBJECT: subject_converted,
                    O365_PARAM_BODY: body_converted,
                },
            },
            "runAfter": {},
        }
        self._converted_count += 1
        return pa_name, definition

    def _map_request_approval(self, action: Action) -> tuple[str, dict[str, Any]]:
        """Map RequestApproval to 'Start and wait for an approval'.

        # Verify against Microsoft docs: Start and wait for an approval via Approvals connector
        """
        pa_name = self._action_id_to_name[action.id]
        approver_raw = action.settings.get("approver", "")
        title_raw = action.settings.get("task_title", "Approval Request")

        approver_conv, w1 = convert_expression(approver_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        title_conv, w2 = convert_expression(title_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        self._warnings.extend(w1 + w2)

        definition: dict[str, Any] = {
            "type": ACTION_TYPE_OPEN_API_CONNECTION,
            "inputs": {
                "host": {
                    "connectionName": APPROVALS_CONNECTION_NAME,
                    "operationId": APPROVALS_OPERATION_ID_START_AND_WAIT,
                    "apiId": APPROVALS_API_ID,
                },
                "parameters": {
                    APPROVALS_PARAM_TYPE: APPROVALS_TYPE_FIRST_TO_RESPOND,
                    APPROVALS_PARAM_TITLE: title_conv,
                    APPROVALS_PARAM_ASSIGNED_TO: approver_conv,
                },
            },
            "runAfter": {},
        }
        self._converted_count += 1
        return pa_name, definition

    def _map_condition(self, action: Action) -> tuple[str, dict[str, Any]]:
        """Map a Condition action to a Power Automate 'If' action with nested branches.

        # Verify against Microsoft docs: Condition (If) action expression and branch schema
        """
        pa_name = self._action_id_to_name[action.id]

        left_raw = action.settings.get("left", "")
        operator = action.settings.get("operator", "equals").lower()
        right_raw = action.settings.get("right", "")

        left_conv, w1 = convert_expression(left_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        self._warnings.extend(w1)

        # Nintex 'Approved' / 'Rejected' maps to Power Automate approval outcomes 'Approve' / 'Reject'
        # Verify against Microsoft docs: Power Automate approval outcome values
        if right_raw.strip().lower() == "approved":
            right_conv = OUTCOME_APPROVE
        elif right_raw.strip().lower() == "rejected":
            right_conv = OUTCOME_REJECT
        else:
            right_conv, w2 = convert_expression(right_raw, self._action_id_to_name, valid_variables=self._valid_variables)
            self._warnings.extend(w2)

        # Recursively map then_actions and else_actions
        then_dict = self._map_action_list(action.then_actions)
        else_dict = self._map_action_list(action.else_actions)

        # Link sequential runAfter within each branch
        self._link_sequential_actions(then_dict)
        self._link_sequential_actions(else_dict)

        definition: dict[str, Any] = {
            "type": ACTION_TYPE_IF,
            "expression": {
                operator: [left_conv, right_conv],
            },
            "actions": then_dict,
            "else": {
                "actions": else_dict,
            },
            "runAfter": {},
        }
        self._converted_count += 1
        return pa_name, definition

    def _map_set_variable(self, action: Action) -> tuple[str, dict[str, Any]]:
        """Map a SetVariable action to a Power Automate 'Set variable' action.

        # Verify against Microsoft docs: Set variable action schema
        """
        pa_name = self._action_id_to_name[action.id]
        var_name = action.settings.get("variable_name", "")
        var_val_raw = action.settings.get("variable_value", "")

        val_conv, w1 = convert_expression(var_val_raw, self._action_id_to_name, valid_variables=self._valid_variables)
        self._warnings.extend(w1)

        definition: dict[str, Any] = {
            "type": ACTION_TYPE_SET_VARIABLE,
            "inputs": {
                "name": var_name,
                "value": val_conv,
            },
            "runAfter": {},
        }
        self._converted_count += 1
        return pa_name, definition

    # -------------------------------------------------------------------------
    # Mapping Loop & Sequencing
    # -------------------------------------------------------------------------

    def _map_action_list(self, actions: list[Action]) -> dict[str, Any]:
        """Convert a list of Action models into a dictionary of PA action definitions.

        Args:
            actions: Sequence of actions to convert.

        Returns:
            Dictionary mapping sanitized PA action names to their definitions.
        """
        result: dict[str, Any] = {}

        for act in actions:
            if act.type == ActionType.START:
                self._map_start(act)
            elif act.type == ActionType.SEND_EMAIL:
                name, defn = self._map_send_email(act)
                result[name] = defn
            elif act.type == ActionType.REQUEST_APPROVAL:
                name, defn = self._map_request_approval(act)
                result[name] = defn
            elif act.type == ActionType.CONDITION:
                name, defn = self._map_condition(act)
                result[name] = defn
            elif act.type == ActionType.SET_VARIABLE:
                name, defn = self._map_set_variable(act)
                result[name] = defn
            else:
                # Unsupported action: do not guess or merge into converted_actions
                orig_type = act.original_type or act.type.value
                reason = f"Action type '{orig_type}' is unsupported in rule-based mapping."

                # Optional Phase 3 LLM suggestion step
                if self._use_llm:
                    suggestion = suggest_conversion(act, client=self._llm_client)
                    if suggestion is not None:
                        self._llm_suggestions.append(
                            ActionSuggestionItem(
                                action_id=act.id,
                                action_name=act.name,
                                original_type=orig_type,
                                suggestion=suggestion,
                                confidence=suggestion.confidence,
                            )
                        )
                        reason = f"Action type '{orig_type}' is unsupported in rule-based mapping (LLM suggestion available)."

                self._unsupported.append(
                    UnsupportedAction(
                        id=act.id,
                        name=act.name,
                        original_type=orig_type,
                        reason=reason,
                    )
                )

        return result

    def _link_sequential_actions(self, actions_dict: dict[str, Any]) -> None:
        """Configure sequential runAfter dependencies between actions.

        The first action runs immediately (runAfter: {}).
        Each subsequent action runs after the preceding one finishes with status 'Succeeded'.

        # Verify against Microsoft docs: Power Automate runAfter dependencies
        """
        prev_name: str | None = None
        for name, defn in actions_dict.items():
            if prev_name is None:
                defn["runAfter"] = {}
            else:
                defn["runAfter"] = {prev_name: [RUN_AFTER_STATUS_SUCCEEDED]}
            prev_name = name

    def map_workflow(self, workflow: Workflow) -> ConversionResult:
        """Map a parsed Nintex Workflow into a ConversionResult.

        Args:
            workflow: Strongly typed source Workflow model.

        Returns:
            A ConversionResult containing converted actions, trigger, unsupported
            items, warnings, LLM suggestions, and conversion metrics.
        """
        self._action_id_to_name.clear()
        self._all_action_names.clear()
        self._valid_variables = {v.name for v in workflow.variables}
        self._unsupported.clear()
        self._warnings.clear()
        self._llm_suggestions.clear()
        self._converted_count = 0

        # Total count of all actions across the entire workflow tree
        self._total_actions = self._count_actions(workflow.actions)

        # Pre-assign sanitized PA names for expression resolution
        self._pre_register_names(workflow.actions)

        # 1. Map Start action to manual trigger
        # Verify against Microsoft docs: manual Request trigger
        trigger_def = {
            TRIGGER_NAME_MANUAL: {
                "type": TRIGGER_TYPE_REQUEST,
                "kind": TRIGGER_KIND_BUTTON,
                "inputs": {
                    "schema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                },
            }
        }

        # 2. Generate "Initialize variable" actions for each declared variable
        # Verify against Microsoft docs: Initialize variable action
        converted_actions: dict[str, Any] = {}
        for var in workflow.variables:
            var_init_name = _sanitize_action_name(
                f"Initialize_variable_{var.name}", self._all_action_names
            )
            converted_val, w = convert_expression(var.value, self._action_id_to_name, valid_variables=self._valid_variables)
            self._warnings.extend(w)

            converted_actions[var_init_name] = {
                "type": ACTION_TYPE_INITIALIZE_VARIABLE,
                "inputs": {
                    "variables": [
                        {
                            "name": var.name,
                            "type": DEFAULT_VARIABLE_TYPE,
                            "value": converted_val,
                        }
                    ]
                },
                "runAfter": {},
            }

        # 3. Map top-level workflow actions
        mapped_body_actions = self._map_action_list(workflow.actions)
        converted_actions.update(mapped_body_actions)

        # 4. Link all sequential actions in root converted_actions with runAfter
        self._link_sequential_actions(converted_actions)

        # 5. Compute metrics
        coverage = (
            round((self._converted_count / self._total_actions) * 100.0, 2)
            if self._total_actions > 0
            else 100.0
        )

        return ConversionResult(
            flow_name=workflow.name,
            trigger=trigger_def,
            converted_actions=converted_actions,
            unsupported=self._unsupported,
            warnings=self._warnings,
            total_actions=self._total_actions,
            converted_count=self._converted_count,
            coverage_percent=coverage,
            use_llm=self._use_llm,
            llm_suggestions=self._llm_suggestions,
        )


def map_workflow(
    workflow: Workflow,
    use_llm: bool = False,
    llm_client: Any = None,
) -> ConversionResult:
    """Convenience function to map a workflow using WorkflowMapper.

    Args:
        workflow: Strongly typed source Workflow model.
        use_llm: Whether to invoke the LLM for unsupported actions (default False).
        llm_client: Optional injected OpenAI client for testing.

    Returns:
        The resulting ConversionResult.
    """
    mapper = WorkflowMapper(use_llm=use_llm, llm_client=llm_client)
    return mapper.map_workflow(workflow)
