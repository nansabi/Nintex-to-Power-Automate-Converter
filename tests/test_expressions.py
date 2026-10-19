"""Unit tests for Nintex-to-Power-Automate expression conversion.

Tests:
- Whole-value variable expression conversion
- In-text variable string interpolation
- Action outcome output reference conversion
- Unknown action ID warning handling
- Unknown reference type warning handling
- Malformed reference warning handling
"""

from src.expressions import convert_expression


def test_whole_value_variable_expression() -> None:
    """Test that a whole-value variable reference maps to @variables('Name')."""
    text = "{Variable:ApproverEmail}"
    action_names: dict[str, str] = {}
    converted, warnings = convert_expression(text, action_names)

    assert converted == "@variables('ApproverEmail')"
    assert len(warnings) == 0


def test_in_text_variable_expression() -> None:
    """Test that in-text variable references map to @{variables('Name')} interpolation."""
    text = "Dear {Variable:EmployeeName}, your request for {Variable:DaysCount} days is pending."
    action_names: dict[str, str] = {}
    converted, warnings = convert_expression(text, action_names)

    expected = "Dear @{variables('EmployeeName')}, your request for @{variables('DaysCount')} days is pending."
    assert converted == expected
    assert len(warnings) == 0


def test_action_outcome_whole_value() -> None:
    """Test that {Action:act-2.Outcome} maps to @body('<PA_Name>')?['outcome']."""
    text = "{Action:act-2.Outcome}"
    action_names = {"act-2": "Manager_Approval"}
    converted, warnings = convert_expression(text, action_names)

    assert converted == "@body('Manager_Approval')?['outcome']"
    assert len(warnings) == 0


def test_action_outcome_in_text() -> None:
    """Test that {Action:act-2.Outcome} inside text maps to @{body('<PA_Name>')?['outcome']}."""
    text = "Decision was {Action:act-2.Outcome} by manager"
    action_names = {"act-2": "Manager_Approval"}
    converted, warnings = convert_expression(text, action_names)

    assert converted == "Decision was @{body('Manager_Approval')?['outcome']} by manager"
    assert len(warnings) == 0


def test_unknown_action_id_returns_warning() -> None:
    """Test that referencing an unmapped action ID is not guessed and logs a warning."""
    text = "{Action:act-99.Outcome}"
    action_names = {"act-2": "Manager_Approval"}
    converted, warnings = convert_expression(text, action_names)

    # Reference remains untouched
    assert converted == "{Action:act-99.Outcome}"
    assert len(warnings) == 1
    assert "act-99" in warnings[0]


def test_unknown_reference_type_returns_warning() -> None:
    """Test that unrecognized reference schemes log a warning and remain unchanged."""
    text = "Prefix {CustomScheme:CustomField} Suffix"
    action_names: dict[str, str] = {}
    converted, warnings = convert_expression(text, action_names)

    assert converted == text
    assert len(warnings) == 1
    assert "CustomScheme" in warnings[0]


def test_malformed_action_reference_returns_warning() -> None:
    """Test that malformed action references without dot separator log a warning."""
    text = "Status is {Action:act-2}"
    action_names = {"act-2": "Manager_Approval"}
    converted, warnings = convert_expression(text, action_names)

    assert converted == text
    assert len(warnings) == 1
    assert "Malformed" in warnings[0]


def test_plain_text_without_expressions() -> None:
    """Test that plain text without references is unaffected."""
    text = "This is a plain message with no special tokens."
    action_names: dict[str, str] = {}
    converted, warnings = convert_expression(text, action_names)

    assert converted == text
    assert len(warnings) == 0
