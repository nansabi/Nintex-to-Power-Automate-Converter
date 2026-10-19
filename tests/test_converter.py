"""Integration and mapper tests for Nintex-to-Power-Automate Phase 2.

Covers:
- Mapping of all 5 supported action types (Start, SendEmail, RequestApproval, Condition, SetVariable)
- Generation of 'Initialize variable' actions for declared variables
- Sample 01 conversion reaching 100% coverage
- Sample 04 reporting Loop as unsupported with coverage under 100% and needs_manual_review=True
- Assertion that unknown actions are never silently dropped
- Generator produces valid JSON with correct sequential runAfter links
- CLI convert command execution
"""

import json
import subprocess
import sys
from pathlib import Path

from src.generator import generate_flow_dict, generate_flow_json
from src.mapper import WorkflowMapper, map_workflow
from src.models import Action, ActionType, Variable, Workflow
from src.parser import parse_workflow

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "samples"


def test_mapper_start_action_creates_trigger() -> None:
    """Test that a Start action maps to a manual request trigger."""
    wf = Workflow(
        name="Trigger Test",
        actions=[Action(id="act-1", type=ActionType.START, name="Start Flow")],
    )
    result = map_workflow(wf)

    assert result.total_actions == 1
    assert result.converted_count == 1
    assert result.coverage_percent == 100.0
    assert "manual" in result.trigger
    assert result.trigger["manual"]["type"] == "Request"


def test_mapper_send_email_action() -> None:
    """Test that SendEmail maps to Office 365 Outlook 'Send an email (V2)'."""
    wf = Workflow(
        name="Email Test",
        actions=[
            Action(
                id="act-1",
                type=ActionType.SEND_EMAIL,
                name="Send Notification",
                settings={
                    "to": "test@example.com",
                    "subject": "Greetings",
                    "body": "Hello world",
                },
            )
        ],
    )
    result = map_workflow(wf)

    assert "Send_Notification" in result.converted_actions
    email_act = result.converted_actions["Send_Notification"]
    assert email_act["type"] == "OpenApiConnection"
    params = email_act["inputs"]["parameters"]
    assert params["emailMessage/To"] == "test@example.com"
    assert params["emailMessage/Subject"] == "Greetings"
    assert params["emailMessage/Body"] == "Hello world"


def test_mapper_request_approval_action() -> None:
    """Test that RequestApproval maps to 'Start and wait for an approval'."""
    wf = Workflow(
        name="Approval Test",
        actions=[
            Action(
                id="act-1",
                type=ActionType.REQUEST_APPROVAL,
                name="Manager Review",
                settings={
                    "approver": "boss@example.com",
                    "task_title": "Expense Approval",
                },
            )
        ],
    )
    result = map_workflow(wf)

    assert "Manager_Review" in result.converted_actions
    appr_act = result.converted_actions["Manager_Review"]
    assert appr_act["type"] == "OpenApiConnection"
    params = appr_act["inputs"]["parameters"]
    assert params["assignedTo"] == "boss@example.com"
    assert params["title"] == "Expense Approval"
    assert params["approvalType"] == "ApproveRejectFirstToRespond"


def test_mapper_condition_action_and_outcome_mapping() -> None:
    """Test Condition action mapping with approval outcome transformation (Approved -> Approve)."""
    wf = Workflow(
        name="Condition Test",
        actions=[
            Action(
                id="act-1",
                type=ActionType.REQUEST_APPROVAL,
                name="Manager Approval",
                settings={"approver": "boss@example.com"},
            ),
            Action(
                id="act-2",
                type=ActionType.CONDITION,
                name="Is Approved",
                settings={
                    "left": "{Action:act-1.Outcome}",
                    "operator": "equals",
                    "right": "Approved",
                },
                then_actions=[
                    Action(
                        id="act-3",
                        type=ActionType.SEND_EMAIL,
                        name="Approved Email",
                        settings={"to": "user@example.com"},
                    )
                ],
                else_actions=[
                    Action(
                        id="act-4",
                        type=ActionType.SEND_EMAIL,
                        name="Rejected Email",
                        settings={"to": "user@example.com"},
                    )
                ],
            ),
        ],
    )
    result = map_workflow(wf)

    assert "Is_Approved" in result.converted_actions
    cond_act = result.converted_actions["Is_Approved"]
    assert cond_act["type"] == "If"

    # Expression maps left to body outcome and right 'Approved' to 'Approve'
    expr = cond_act["expression"]
    assert "equals" in expr
    assert expr["equals"][0] == "@body('Manager_Approval')?['outcome']"
    assert expr["equals"][1] == "Approve"

    # Nested actions in then and else
    assert "Approved_Email" in cond_act["actions"]
    assert "Rejected_Email" in cond_act["else"]["actions"]


def test_mapper_set_variable_and_initialize_variable() -> None:
    """Test SetVariable action and automatic generation of InitializeVariable for declared variables."""
    wf = Workflow(
        name="Var Test",
        variables=[Variable(name="StatusMsg", value="Pending")],
        actions=[
            Action(
                id="act-1",
                type=ActionType.SET_VARIABLE,
                name="Update Status",
                settings={
                    "variable_name": "StatusMsg",
                    "variable_value": "Completed",
                },
            )
        ],
    )
    result = map_workflow(wf)

    # Must contain Initialize_variable_StatusMsg
    assert "Initialize_variable_StatusMsg" in result.converted_actions
    init_act = result.converted_actions["Initialize_variable_StatusMsg"]
    assert init_act["type"] == "InitializeVariable"
    assert init_act["inputs"]["variables"][0]["name"] == "StatusMsg"
    assert init_act["inputs"]["variables"][0]["value"] == "Pending"

    # Must contain Update_Status
    assert "Update_Status" in result.converted_actions
    set_act = result.converted_actions["Update_Status"]
    assert set_act["type"] == "SetVariable"
    assert set_act["inputs"]["name"] == "StatusMsg"
    assert set_act["inputs"]["value"] == "Completed"


def test_sample_01_full_conversion_100_percent() -> None:
    """Test that sample 01 converts completely with 100% coverage and no unsupported actions."""
    wf = parse_workflow(SAMPLES_DIR / "01_leave_approval.xml")
    result = map_workflow(wf)

    assert result.flow_name == "Leave Request Approval"
    assert result.total_actions == 5
    assert result.converted_count == 5
    assert result.coverage_percent == 100.0
    assert len(result.unsupported) == 0

    flow_dict = generate_flow_dict(result)
    assert flow_dict["needs_manual_review"] is False


def test_sample_04_unsupported_loop_reports_manual_review() -> None:
    """Test that sample 04 flags the Loop action as unsupported with needs_manual_review=True."""
    wf = parse_workflow(SAMPLES_DIR / "04_unsupported_loop.xml")
    result = map_workflow(wf)

    assert result.flow_name == "Unsupported Loop Workflow"
    assert result.total_actions == 3
    assert result.converted_count == 2
    assert result.coverage_percent < 100.0
    assert len(result.unsupported) == 1

    unsupported_item = result.unsupported[0]
    assert unsupported_item.id == "act-2"
    assert unsupported_item.original_type == "Loop"
    assert "unsupported" in unsupported_item.reason.lower()

    flow_dict = generate_flow_dict(result)
    assert flow_dict["needs_manual_review"] is True


def test_unknown_action_is_never_silently_dropped() -> None:
    """Verify that any unrecognized action is recorded in unsupported and not ignored."""
    wf = Workflow(
        name="Unknown Test",
        actions=[
            Action(
                id="act-custom",
                type=ActionType.UNKNOWN,
                name="Custom Plugin Step",
            )
        ],
    )
    result = map_workflow(wf)

    assert result.converted_count == 0
    assert len(result.unsupported) == 1
    assert result.unsupported[0].id == "act-custom"
    assert result.unsupported[0].name == "Custom Plugin Step"
    assert "unsupported" in result.unsupported[0].reason.lower()


def test_generator_run_after_linking_and_valid_json() -> None:
    """Verify that sequential actions are correctly chained with runAfter in generated JSON."""
    wf = parse_workflow(SAMPLES_DIR / "02_simple_email.xml")
    result = map_workflow(wf)
    json_text = generate_flow_json(result)

    parsed = json.loads(json_text)
    assert parsed["name"] == "Simple Email Notification"
    assert "definition" in parsed
    assert "triggers" in parsed["definition"]
    actions = parsed["definition"]["actions"]

    # In sample 02: declared variable initialized, then Send_Welcome_Email
    action_names = list(actions.keys())
    assert len(action_names) >= 2

    first_act = actions[action_names[0]]
    assert first_act["runAfter"] == {}

    second_act = actions[action_names[1]]
    assert action_names[0] in second_act["runAfter"]
    assert second_act["runAfter"][action_names[0]] == ["Succeeded"]


def test_cli_convert_execution(tmp_path: Path) -> None:
    """Test CLI invocation of convert_workflow_file."""
    output_file = tmp_path / "test_out.json"
    cmd = [
        sys.executable,
        "-m",
        "src.convert",
        str(SAMPLES_DIR / "01_leave_approval.xml"),
        "-o",
        str(output_file),
    ]
    res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, check=False)

    assert res.returncode == 0
    assert "Coverage:               100.0%" in res.stdout
    assert "Manual Review Needed:   No" in res.stdout
    assert output_file.exists()

    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["name"] == "Leave Request Approval"
    assert data["needs_manual_review"] is False


def test_sample_05_conversion_full_coverage() -> None:
    """Test sample 05 converts with 100% coverage and nested condition structure."""
    wf = parse_workflow(SAMPLES_DIR / "05_nested_conditions.xml")
    result = map_workflow(wf)
    assert result.flow_name == "Nested Conditions Workflow"
    assert result.total_actions == 7
    assert result.converted_count == 7
    assert result.coverage_percent == 100.0
    assert len(result.unsupported) == 0


def test_sample_06_conversion_full_coverage() -> None:
    """Test sample 06 converts with 100% coverage."""
    wf = parse_workflow(SAMPLES_DIR / "06_variable_in_condition.xml")
    result = map_workflow(wf)
    assert result.flow_name == "Variable In Condition Workflow"
    assert result.total_actions == 5
    assert result.converted_count == 5
    assert result.coverage_percent == 100.0
    assert len(result.unsupported) == 0


def test_sample_07_conversion_reports_undeclared_variable_warning() -> None:
    """Test sample 07 produces warning for undeclared variable without failing."""
    wf = parse_workflow(SAMPLES_DIR / "07_bad_reference.xml")
    result = map_workflow(wf)
    assert result.flow_name == "Bad Reference Workflow"
    assert result.total_actions == 2
    assert result.converted_count == 2
    assert len(result.warnings) == 1
    assert "NonExistentVariable" in result.warnings[0]


def test_sample_08_conversion_multiple_unsupported_actions() -> None:
    """Test sample 08 reports both Loop and WebServiceCall as unsupported."""
    wf = parse_workflow(SAMPLES_DIR / "08_multiple_unsupported.xml")
    result = map_workflow(wf)
    assert result.flow_name == "Multiple Unsupported Actions Workflow"
    assert result.total_actions == 5
    assert result.converted_count == 3
    assert result.coverage_percent == 60.0
    assert len(result.unsupported) == 2
    unsupported_types = {u.original_type for u in result.unsupported}
    assert unsupported_types == {"Loop", "WebServiceCall"}

