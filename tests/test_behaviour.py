"""Behavioural validation tests comparing Nintex and Power Automate simulation traces.

Proves that converted workflows preserve identical runtime behaviour to the original
by executing both simulators against realistic input scenarios:
- Sample 01 (Leave Approval: Approved vs Rejected paths)
- Sample 02 (Simple Email notification)
- Sample 03 (SetVariable mutation and referencing)
- Sample 05 (Nested Conditions: Expedited, Standard, and Rejected paths)
- Sample 06 (Variable evaluated in condition)
- Negative test: Confirms that deliberate changes to flow logic cause tests to fail
"""

from pathlib import Path
import pytest

from src.generator import generate_flow_dict
from src.mapper import map_workflow
from src.parser import parse_workflow
from src.simulate import simulate_nintex, simulate_power_automate

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "samples"


def test_sample_01_behaviour_approved() -> None:
    """Test sample 01 when manager approves: approval notice sent to employee."""
    wf = parse_workflow(SAMPLES_DIR / "01_leave_approval.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    scenario = {"approval_outcome": "Approved"}
    trace_nintex = simulate_nintex(wf, scenario)
    trace_pa = simulate_power_automate(pa_dict, scenario)

    assert len(trace_nintex.emails_sent) == 1
    assert len(trace_pa.emails_sent) == 1
    assert trace_nintex.emails_sent[0] == trace_pa.emails_sent[0]
    assert trace_pa.emails_sent[0].subject == "Leave Request Approved"
    assert trace_pa.emails_sent[0].to == "alice@company.com"
    assert trace_nintex.approval_outcomes_used == trace_pa.approval_outcomes_used


def test_sample_01_behaviour_rejected() -> None:
    """Test sample 01 when manager rejects: rejection notice sent to employee."""
    wf = parse_workflow(SAMPLES_DIR / "01_leave_approval.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    scenario = {"approval_outcome": "Rejected"}
    trace_nintex = simulate_nintex(wf, scenario)
    trace_pa = simulate_power_automate(pa_dict, scenario)

    assert len(trace_nintex.emails_sent) == 1
    assert len(trace_pa.emails_sent) == 1
    assert trace_nintex.emails_sent[0] == trace_pa.emails_sent[0]
    assert trace_pa.emails_sent[0].subject == "Leave Request Rejected"
    assert trace_pa.emails_sent[0].to == "alice@company.com"


def test_sample_02_behaviour_simple_email() -> None:
    """Test sample 02 dispatches welcome email to the recipient."""
    wf = parse_workflow(SAMPLES_DIR / "02_simple_email.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    trace_nintex = simulate_nintex(wf)
    trace_pa = simulate_power_automate(pa_dict)

    assert len(trace_nintex.emails_sent) == 1
    assert trace_nintex.emails_sent[0] == trace_pa.emails_sent[0]
    assert trace_pa.emails_sent[0].to == "team@company.com"
    assert trace_pa.emails_sent[0].subject == "Welcome to the Team"


def test_sample_03_behaviour_set_variable() -> None:
    """Test sample 03 updates variable and reflects it in email body."""
    wf = parse_workflow(SAMPLES_DIR / "03_set_variable.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    trace_nintex = simulate_nintex(wf)
    trace_pa = simulate_power_automate(pa_dict)

    assert trace_nintex.emails_sent == trace_pa.emails_sent
    assert trace_nintex.variables_set["NotificationMessage"] == trace_pa.variables_set["NotificationMessage"]
    assert "maintenance is scheduled" in trace_pa.emails_sent[0].body.lower()


def test_sample_05_behaviour_expedited_notice() -> None:
    """Test sample 05: Approved + High Priority -> Expedited Notice."""
    wf = parse_workflow(SAMPLES_DIR / "05_nested_conditions.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    scenario = {"approval_outcome": "Approved", "RequestPriority": "High"}
    trace_nintex = simulate_nintex(wf, scenario)
    trace_pa = simulate_power_automate(pa_dict, scenario)

    assert trace_nintex.emails_sent == trace_pa.emails_sent
    assert trace_pa.emails_sent[0].subject == "Expedited Approval Confirmed"
    assert "expedited" in trace_pa.emails_sent[0].body.lower()


def test_sample_05_behaviour_standard_notice() -> None:
    """Test sample 05: Approved + Low Priority -> Standard Notice."""
    wf = parse_workflow(SAMPLES_DIR / "05_nested_conditions.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    scenario = {"approval_outcome": "Approved", "RequestPriority": "Low"}
    trace_nintex = simulate_nintex(wf, scenario)
    trace_pa = simulate_power_automate(pa_dict, scenario)

    assert trace_nintex.emails_sent == trace_pa.emails_sent
    assert trace_pa.emails_sent[0].subject == "Standard Approval Confirmed"


def test_sample_05_behaviour_rejected() -> None:
    """Test sample 05: Rejected -> Rejection Notice."""
    wf = parse_workflow(SAMPLES_DIR / "05_nested_conditions.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    scenario = {"approval_outcome": "Rejected"}
    trace_nintex = simulate_nintex(wf, scenario)
    trace_pa = simulate_power_automate(pa_dict, scenario)

    assert trace_nintex.emails_sent == trace_pa.emails_sent
    assert trace_pa.emails_sent[0].subject == "Request Not Approved"


def test_sample_06_behaviour_vip_promotion() -> None:
    """Test sample 06: User is promoted to VIP and receives VIP welcome email."""
    wf = parse_workflow(SAMPLES_DIR / "06_variable_in_condition.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    trace_nintex = simulate_nintex(wf)
    trace_pa = simulate_power_automate(pa_dict)

    assert trace_nintex.emails_sent == trace_pa.emails_sent
    assert trace_pa.emails_sent[0].subject == "Welcome to VIP Access"


def test_deliberate_breaking_change_fails_validation() -> None:
    """Deliberately corrupt a converted flow definition and verify that trace comparison fails."""
    wf = parse_workflow(SAMPLES_DIR / "01_leave_approval.xml")
    pa_dict = generate_flow_dict(map_workflow(wf))

    # Sabotage the approval email recipient
    cond_action = pa_dict["definition"]["actions"]["Check_If_Approved"]
    send_act = cond_action["actions"]["Send_Approval_Notice"]
    send_act["inputs"]["parameters"]["emailMessage/To"] = "sabotaged_wrong_person@evil.com"

    scenario = {"approval_outcome": "Approved"}
    trace_nintex = simulate_nintex(wf, scenario)
    trace_pa = simulate_power_automate(pa_dict, scenario)

    # Must fail!
    with pytest.raises(AssertionError):
        assert trace_nintex.emails_sent == trace_pa.emails_sent
