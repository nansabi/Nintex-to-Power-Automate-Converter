"""Workflow execution simulators for Nintex models and Power Automate flow definitions.

Simulates workflow execution with scripted inputs to verify behavioural fidelity:
  1. simulate_nintex: executes a parsed Nintex Workflow model.
  2. simulate_power_automate: executes a generated Power Automate flow JSON.

Both record a trace of side effects (emails sent, approval decisions, variables modified)
to prove that converted workflows preserve the exact runtime behaviour of the original.
"""

from __future__ import annotations

import json
import re
from typing import Any
from pydantic import BaseModel, Field

from src.models import Action, ActionType, Workflow
from src.pa_constants import (
    ACTION_TYPE_IF,
    ACTION_TYPE_INITIALIZE_VARIABLE,
    ACTION_TYPE_OPEN_API_CONNECTION,
    ACTION_TYPE_SET_VARIABLE,
    APPROVALS_OPERATION_ID_START_AND_WAIT,
    O365_OPERATION_ID_SEND_EMAIL_V2,
    O365_PARAM_BODY,
    O365_PARAM_SUBJECT,
    O365_PARAM_TO,
)


class EmailRecord(BaseModel):
    """Trace record of an email dispatched during workflow simulation."""

    to: str
    subject: str
    body: str


class SimulationTrace(BaseModel):
    """Structured execution trace capturing all side-effects and state transitions."""

    emails_sent: list[EmailRecord] = Field(default_factory=list)
    approval_outcomes_used: list[str] = Field(default_factory=list)
    variables_set: dict[str, Any] = Field(default_factory=dict)
    actions_executed: list[str] = Field(default_factory=list)


# =============================================================================
# Nintex Simulation Engine
# =============================================================================

def _resolve_nintex_text(
    template: str,
    variables: dict[str, Any],
    approval_outcome: str,
) -> str:
    """Resolve Nintex-style tokens ({Variable:...}, {Action:...Outcome}) in a string."""
    if not isinstance(template, str) or not template:
        return ""

    result = template

    # Replace variable references
    def _replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1).strip()
        return str(variables.get(var_name, match.group(0)))

    result = re.sub(r"\{Variable:([a-zA-Z0-9_\- ]+)\}", _replace_var, result)

    # Replace action outcome references
    result = re.sub(r"\{Action:[a-zA-Z0-9_\-]+\.Outcome\}", approval_outcome, result, flags=re.IGNORECASE)

    return result


def _execute_nintex_action(
    action: Action,
    variables: dict[str, Any],
    approval_outcome: str,
    trace: SimulationTrace,
) -> None:
    """Execute a single Nintex action and update the simulation trace."""
    trace.actions_executed.append(action.id)

    if action.type == ActionType.START:
        return

    elif action.type == ActionType.REQUEST_APPROVAL:
        trace.approval_outcomes_used.append(approval_outcome)

    elif action.type == ActionType.SET_VARIABLE:
        var_name = action.settings.get("variable_name", "")
        raw_val = action.settings.get("variable_value", "")
        resolved_val = _resolve_nintex_text(raw_val, variables, approval_outcome)
        variables[var_name] = resolved_val
        trace.variables_set[var_name] = resolved_val

    elif action.type == ActionType.SEND_EMAIL:
        to = _resolve_nintex_text(action.settings.get("to", ""), variables, approval_outcome)
        subject = _resolve_nintex_text(action.settings.get("subject", ""), variables, approval_outcome)
        body = _resolve_nintex_text(action.settings.get("body", ""), variables, approval_outcome)
        trace.emails_sent.append(EmailRecord(to=to, subject=subject, body=body))

    elif action.type == ActionType.CONDITION:
        left = _resolve_nintex_text(action.settings.get("left", ""), variables, approval_outcome)
        right = _resolve_nintex_text(action.settings.get("right", ""), variables, approval_outcome)
        op = action.settings.get("operator", "equals").lower()

        if op in ("equals", "=="):
            condition_met = (left.strip().lower() == right.strip().lower())
        elif op in ("notequals", "!="):
            condition_met = (left.strip().lower() != right.strip().lower())
        else:
            condition_met = False

        branch_actions = action.then_actions if condition_met else action.else_actions
        for child in branch_actions:
            _execute_nintex_action(child, variables, approval_outcome, trace)


def simulate_nintex(
    workflow: Workflow,
    inputs: dict[str, Any] | None = None,
) -> SimulationTrace:
    """Simulate execution of a parsed Nintex workflow model with scripted inputs.

    Args:
        workflow: The parsed Workflow model to simulate.
        inputs: Input dictionary (e.g. {'approval_outcome': 'Approved'}).

    Returns:
        SimulationTrace capturing emails sent, variables modified, and outcomes used.
    """
    inputs = inputs or {}
    approval_outcome = inputs.get("approval_outcome", "Approved")

    variables: dict[str, Any] = {v.name: v.value for v in workflow.variables}
    # Allow input dictionary to pre-populate / override variables
    for k, v in inputs.items():
        if k != "approval_outcome":
            variables[k] = v

    trace = SimulationTrace(variables_set=dict(variables))

    for action in workflow.actions:
        _execute_nintex_action(action, variables, approval_outcome, trace)

    return trace


# =============================================================================
# Power Automate Simulation Engine
# =============================================================================

def _resolve_pa_text(
    template: str,
    variables: dict[str, Any],
    pa_outcome: str,
) -> str:
    """Resolve Power Automate expressions (@variables(...), @body(...)['outcome'])."""
    if not isinstance(template, str) or not template:
        return ""

    stripped = template.strip()

    # Exact whole-expression checks
    if stripped.startswith("@variables('") and stripped.endswith("')"):
        var_name = stripped[len("@variables('"):-2]
        return str(variables.get(var_name, ""))

    if "@body(" in stripped and "['outcome']" in stripped:
        if stripped.startswith("@body("):
            return pa_outcome

    # In-text replacements
    result = template

    def _replace_pa_var(match: re.Match[str]) -> str:
        var_name = match.group(1).strip()
        return str(variables.get(var_name, ""))

    result = re.sub(r"@\{variables\('([^']+)'\)\}", _replace_pa_var, result)
    result = re.sub(r"@\{body\([^)]+\)\?\['outcome'\]\}", pa_outcome, result)

    return result


def _execute_pa_action_dict(
    actions_dict: dict[str, Any],
    variables: dict[str, Any],
    approval_outcome: str,
    pa_outcome: str,
    trace: SimulationTrace,
) -> None:
    """Execute a dictionary of Power Automate actions sequentially."""
    for action_name, action_def in actions_dict.items():
        trace.actions_executed.append(action_name)
        act_type = action_def.get("type")
        inputs_block = action_def.get("inputs", {})

        if act_type == ACTION_TYPE_INITIALIZE_VARIABLE:
            for var_entry in inputs_block.get("variables", []):
                v_name = var_entry.get("name")
                if v_name not in variables or variables[v_name] is None:
                    v_val = _resolve_pa_text(var_entry.get("value", ""), variables, pa_outcome)
                    variables[v_name] = v_val
                    trace.variables_set[v_name] = v_val
                else:
                    trace.variables_set[v_name] = variables[v_name]

        elif act_type == ACTION_TYPE_SET_VARIABLE:
            v_name = inputs_block.get("name")
            v_val = _resolve_pa_text(inputs_block.get("value", ""), variables, pa_outcome)
            variables[v_name] = v_val
            trace.variables_set[v_name] = v_val

        elif act_type == ACTION_TYPE_OPEN_API_CONNECTION:
            op_id = inputs_block.get("host", {}).get("operationId", "")
            params = inputs_block.get("parameters", {})

            if op_id == O365_OPERATION_ID_SEND_EMAIL_V2:
                to = _resolve_pa_text(params.get(O365_PARAM_TO, ""), variables, pa_outcome)
                subject = _resolve_pa_text(params.get(O365_PARAM_SUBJECT, ""), variables, pa_outcome)
                body = _resolve_pa_text(params.get(O365_PARAM_BODY, ""), variables, pa_outcome)
                trace.emails_sent.append(EmailRecord(to=to, subject=subject, body=body))

            elif op_id == APPROVALS_OPERATION_ID_START_AND_WAIT:
                trace.approval_outcomes_used.append(approval_outcome)

        elif act_type == ACTION_TYPE_IF:
            expression = action_def.get("expression", {})
            condition_met = False

            for op, operands in expression.items():
                if len(operands) >= 2:
                    left = _resolve_pa_text(str(operands[0]), variables, pa_outcome)
                    right = _resolve_pa_text(str(operands[1]), variables, pa_outcome)
                    if op == "equals":
                        condition_met = (left.strip().lower() == right.strip().lower())
                    elif op == "notequals":
                        condition_met = (left.strip().lower() != right.strip().lower())

            branch = action_def.get("actions", {}) if condition_met else action_def.get("else", {}).get("actions", {})
            _execute_pa_action_dict(branch, variables, approval_outcome, pa_outcome, trace)


def simulate_power_automate(
    flow_json: dict[str, Any] | str,
    inputs: dict[str, Any] | None = None,
) -> SimulationTrace:
    """Simulate execution of a generated Power Automate flow with scripted inputs.

    Args:
        flow_json: Flow dictionary or JSON string.
        inputs: Input dictionary (e.g. {'approval_outcome': 'Approved'}).

    Returns:
        SimulationTrace capturing emails sent, variables modified, and outcomes used.
    """
    inputs = inputs or {}
    approval_outcome = inputs.get("approval_outcome", "Approved")

    # Map approval outcome to Power Automate vocabulary: Approved -> Approve, Rejected -> Reject
    if approval_outcome.strip().lower() == "approved":
        pa_outcome = "Approve"
    elif approval_outcome.strip().lower() == "rejected":
        pa_outcome = "Reject"
    else:
        pa_outcome = approval_outcome

    if isinstance(flow_json, str):
        flow_data = json.loads(flow_json)
    else:
        flow_data = flow_json

    variables: dict[str, Any] = {}
    for k, v in inputs.items():
        if k != "approval_outcome":
            variables[k] = v

    trace = SimulationTrace(variables_set=dict(variables))
    actions_block = flow_data.get("definition", {}).get("actions", {})

    _execute_pa_action_dict(actions_block, variables, approval_outcome, pa_outcome, trace)

    return trace
