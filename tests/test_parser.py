"""Unit tests for the Nintex workflow parser.

Covers:
- Sample 01 (Leave Approval with condition branches)
- Sample 02 (Simple email notification)
- Sample 03 (SetVariable and variable references)
- Sample 04 (Unsupported Loop action mapping to UNKNOWN)
- Malformed XML error handling
- Missing action id error handling
- Missing workflow name error handling
- Missing action type error handling
- Deeply nested Condition branches (Then and Else)
- File not found handling
- CLI tree output
"""

import subprocess
import sys
from pathlib import Path

import pytest
from src.models import ActionType
from src.parser import WorkflowParseError, parse_workflow, parse_workflow_from_string

# Base directory for the test suite (nintex-converter/)
BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "samples"


def test_sample_01_leave_approval() -> None:
    """Test parsing 01_leave_approval.xml with Start, Approval, and Condition branches."""
    sample_file = SAMPLES_DIR / "01_leave_approval.xml"
    wf = parse_workflow(sample_file)

    # Verify workflow metadata
    assert wf.name == "Leave Request Approval"

    # Verify variables
    var_map = {v.name: v.value for v in wf.variables}
    assert "EmployeeName" in var_map
    assert var_map["ApproverEmail"] == "manager@company.com"
    assert var_map["EmployeeEmail"] == "alice@company.com"

    # Verify root actions sequence: Start -> RequestApproval -> Condition
    assert len(wf.actions) == 3

    act_start = wf.actions[0]
    assert act_start.id == "act-1"
    assert act_start.type == ActionType.START
    assert act_start.name == "Workflow Start"

    act_approval = wf.actions[1]
    assert act_approval.id == "act-2"
    assert act_approval.type == ActionType.REQUEST_APPROVAL
    assert act_approval.name == "Manager Approval"
    assert act_approval.settings["approver"] == "{Variable:ApproverEmail}"
    assert act_approval.settings["due_in_days"] == "3"

    act_cond = wf.actions[2]
    assert act_cond.id == "act-3"
    assert act_cond.type == ActionType.CONDITION
    assert act_cond.name == "Check If Approved"
    assert act_cond.settings["operator"] == "equals"
    assert act_cond.settings["right"] == "Approved"

    # Verify Then branch
    assert len(act_cond.then_actions) == 1
    then_act = act_cond.then_actions[0]
    assert then_act.id == "act-4"
    assert then_act.type == ActionType.SEND_EMAIL
    assert then_act.name == "Send Approval Notice"
    assert then_act.settings["to"] == "{Variable:EmployeeEmail}"
    assert "approved" in then_act.settings["body"].lower()

    # Verify Else branch
    assert len(act_cond.else_actions) == 1
    else_act = act_cond.else_actions[0]
    assert else_act.id == "act-5"
    assert else_act.type == ActionType.SEND_EMAIL
    assert else_act.name == "Send Rejection Notice"
    assert else_act.settings["to"] == "{Variable:EmployeeEmail}"
    assert "rejected" in else_act.settings["body"].lower()


def test_sample_02_simple_email() -> None:
    """Test parsing 02_simple_email.xml with Start and SendEmail actions."""
    sample_file = SAMPLES_DIR / "02_simple_email.xml"
    wf = parse_workflow(sample_file)

    assert wf.name == "Simple Email Notification"
    assert len(wf.variables) == 1
    assert wf.variables[0].name == "RecipientEmail"
    assert wf.variables[0].value == "team@company.com"

    assert len(wf.actions) == 2
    assert wf.actions[0].type == ActionType.START
    assert wf.actions[1].type == ActionType.SEND_EMAIL
    assert wf.actions[1].settings["subject"] == "Welcome to the Team"
    assert wf.actions[1].settings["to"] == "{Variable:RecipientEmail}"


def test_sample_03_set_variable() -> None:
    """Test parsing 03_set_variable.xml with SetVariable and variable references."""
    sample_file = SAMPLES_DIR / "03_set_variable.xml"
    wf = parse_workflow(sample_file)

    assert wf.name == "Set Variable and Send Email"
    assert len(wf.variables) == 2

    assert len(wf.actions) == 3
    set_var_act = wf.actions[1]
    assert set_var_act.id == "act-2"
    assert set_var_act.type == ActionType.SET_VARIABLE
    assert set_var_act.settings["variable_name"] == "NotificationMessage"
    assert "maintenance" in set_var_act.settings["variable_value"].lower()

    email_act = wf.actions[2]
    assert email_act.type == ActionType.SEND_EMAIL
    assert "{Variable:NotificationMessage}" in email_act.settings["body"]


def test_sample_04_unsupported_loop_produces_unknown_action() -> None:
    """Test that an unsupported action (<Action type="Loop">) maps safely to ActionType.UNKNOWN."""
    sample_file = SAMPLES_DIR / "04_unsupported_loop.xml"
    wf = parse_workflow(sample_file)

    assert wf.name == "Unsupported Loop Workflow"
    assert len(wf.actions) == 3

    loop_act = wf.actions[1]
    assert loop_act.id == "act-2"
    # Must become UNKNOWN without crashing or guessing
    assert loop_act.type == ActionType.UNKNOWN
    assert loop_act.name == "Iterate Through Items"
    assert loop_act.settings["max_iterations"] == "10"

    # Other actions remain unaffected
    assert wf.actions[0].type == ActionType.START
    assert wf.actions[2].type == ActionType.SEND_EMAIL


def test_malformed_xml_raises_error() -> None:
    """Test that malformed XML syntax raises WorkflowParseError with clear message."""
    bad_xml = "<Workflow name='Broken'><Actions><Action id='1' type='Start'></Actions>"
    with pytest.raises(WorkflowParseError) as exc_info:
        parse_workflow_from_string(bad_xml, source_name="bad_xml_test")

    assert "Malformed XML" in str(exc_info.value)


def test_missing_action_id_raises_error() -> None:
    """Test that an action missing an 'id' attribute raises WorkflowParseError."""
    xml_missing_id = """
    <Workflow name="Missing ID Test">
        <Actions>
            <Action type="Start" name="Start Without ID" />
        </Actions>
    </Workflow>
    """
    with pytest.raises(WorkflowParseError) as exc_info:
        parse_workflow_from_string(xml_missing_id)

    assert "missing required 'id' attribute" in str(exc_info.value)


def test_missing_workflow_name_raises_error() -> None:
    """Test that a workflow missing a 'name' attribute raises WorkflowParseError."""
    xml_no_name = """
    <Workflow>
        <Actions>
            <Action id="act-1" type="Start" name="Start" />
        </Actions>
    </Workflow>
    """
    with pytest.raises(WorkflowParseError) as exc_info:
        parse_workflow_from_string(xml_no_name)

    assert "missing required 'name' attribute" in str(exc_info.value)


def test_missing_action_type_raises_error() -> None:
    """Test that an action missing a 'type' attribute raises WorkflowParseError."""
    xml_missing_type = """
    <Workflow name="Missing Type Test">
        <Actions>
            <Action id="act-1" name="Action Without Type" />
        </Actions>
    </Workflow>
    """
    with pytest.raises(WorkflowParseError) as exc_info:
        parse_workflow_from_string(xml_missing_type)

    assert "missing required 'type' attribute" in str(exc_info.value)


def test_nested_condition_branches() -> None:
    """Test deeply nested condition branches (Condition inside a Condition)."""
    nested_xml = """
    <Workflow name="Nested Branches Workflow">
        <Actions>
            <Action id="cond-1" type="Condition" name="Outer Condition">
                <Settings><operator>equals</operator></Settings>
                <Then>
                    <Action id="cond-2" type="Condition" name="Inner Condition">
                        <Settings><operator>greaterThan</operator></Settings>
                        <Then>
                            <Action id="act-inner-then" type="SendEmail" name="Email High Priority">
                                <Settings><to>boss@company.com</to></Settings>
                            </Action>
                        </Then>
                        <Else>
                            <Action id="act-inner-else" type="SendEmail" name="Email Low Priority">
                                <Settings><to>staff@company.com</to></Settings>
                            </Action>
                        </Else>
                    </Action>
                </Then>
                <Else>
                    <Action id="act-outer-else" type="SetVariable" name="Reset Status">
                        <Settings><variable_name>Status</variable_name><variable_value>Reset</variable_value></Settings>
                    </Action>
                </Else>
            </Action>
        </Actions>
    </Workflow>
    """
    wf = parse_workflow_from_string(nested_xml)

    outer_cond = wf.actions[0]
    assert outer_cond.id == "cond-1"
    assert len(outer_cond.then_actions) == 1
    assert len(outer_cond.else_actions) == 1

    inner_cond = outer_cond.then_actions[0]
    assert inner_cond.id == "cond-2"
    assert inner_cond.type == ActionType.CONDITION

    # Check inner then branch
    assert len(inner_cond.then_actions) == 1
    assert inner_cond.then_actions[0].id == "act-inner-then"
    assert inner_cond.then_actions[0].type == ActionType.SEND_EMAIL

    # Check inner else branch
    assert len(inner_cond.else_actions) == 1
    assert inner_cond.else_actions[0].id == "act-inner-else"
    assert inner_cond.else_actions[0].type == ActionType.SEND_EMAIL

    # Check outer else branch
    assert outer_cond.else_actions[0].id == "act-outer-else"
    assert outer_cond.else_actions[0].type == ActionType.SET_VARIABLE


def test_file_not_found_raises_error() -> None:
    """Test that attempting to parse a non-existent file path raises FileNotFoundError."""
    non_existent = SAMPLES_DIR / "non_existent_file.xml"
    with pytest.raises(FileNotFoundError):
        parse_workflow(non_existent)


def test_cli_tree_execution() -> None:
    """Test the CLI output when running 'python -m src.parser samples/01_leave_approval.xml'."""
    cmd = [
        sys.executable,
        "-m",
        "src.parser",
        str(SAMPLES_DIR / "01_leave_approval.xml"),
    ]
    result = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    stdout = result.stdout
    assert "Workflow: Leave Request Approval" in stdout
    assert "[act-1] Start: Workflow Start" in stdout
    assert "[act-2] RequestApproval: Manager Approval" in stdout
    assert "[act-3] Condition: Check If Approved" in stdout
    assert "[THEN branch]:" in stdout
    assert "[act-4] SendEmail: Send Approval Notice" in stdout
    assert "[ELSE branch]:" in stdout
    assert "[act-5] SendEmail: Send Rejection Notice" in stdout


def test_sample_05_nested_conditions() -> None:
    """Test parsing 05_nested_conditions.xml with multi-level nested condition branches."""
    wf = parse_workflow(SAMPLES_DIR / "05_nested_conditions.xml")
    assert wf.name == "Nested Conditions Workflow"
    assert len(wf.variables) == 3
    assert len(wf.actions) == 3  # Start, RequestApproval, Condition
    outer_cond = wf.actions[2]
    assert outer_cond.type == ActionType.CONDITION
    assert len(outer_cond.then_actions) == 1
    inner_cond = outer_cond.then_actions[0]
    assert inner_cond.type == ActionType.CONDITION
    assert len(inner_cond.then_actions) == 1
    assert len(inner_cond.else_actions) == 1
    assert len(outer_cond.else_actions) == 1


def test_sample_06_variable_in_condition() -> None:
    """Test parsing 06_variable_in_condition.xml with SetVariable and condition check."""
    wf = parse_workflow(SAMPLES_DIR / "06_variable_in_condition.xml")
    assert wf.name == "Variable In Condition Workflow"
    assert len(wf.variables) == 2
    assert len(wf.actions) == 3
    assert wf.actions[1].type == ActionType.SET_VARIABLE
    assert wf.actions[2].type == ActionType.CONDITION


def test_sample_07_bad_reference() -> None:
    """Test parsing 07_bad_reference.xml."""
    wf = parse_workflow(SAMPLES_DIR / "07_bad_reference.xml")
    assert wf.name == "Bad Reference Workflow"
    assert len(wf.actions) == 2
    assert wf.actions[1].type == ActionType.SEND_EMAIL


def test_sample_08_multiple_unsupported() -> None:
    """Test parsing 08_multiple_unsupported.xml containing two distinct unsupported actions."""
    wf = parse_workflow(SAMPLES_DIR / "08_multiple_unsupported.xml")
    assert wf.name == "Multiple Unsupported Actions Workflow"
    assert len(wf.actions) == 5
    assert wf.actions[1].type == ActionType.UNKNOWN
    assert wf.actions[1].original_type == "Loop"
    assert wf.actions[3].type == ActionType.UNKNOWN
    assert wf.actions[3].original_type == "WebServiceCall"

