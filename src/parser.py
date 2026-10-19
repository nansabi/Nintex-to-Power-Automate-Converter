"""XML Parser for Nintex-style workflow definitions.

This module is responsible for loading workflow XML files, validating their
structure and required attributes, and converting them into strongly typed
Pydantic models (Workflow, Action, Variable).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from src.models import Action, ActionType, Variable, Workflow


class WorkflowParseError(ValueError):
    """Custom exception raised when XML workflow parsing fails.

    This error indicates either malformed XML syntax or missing required
    attributes/elements in the workflow definition.
    """

    pass


def _parse_settings(settings_elem: ET.Element | None) -> dict[str, Any]:
    """Extract key-value pairs from a <Settings> XML element.

    Supports both formats:
      1. Tag-name style: <to>alice@example.com</to>
      2. Setting-element style: <Setting name="to">alice@example.com</Setting>
         or <Setting name="to" value="alice@example.com" />

    Args:
        settings_elem: The <Settings> XML element, or None if omitted.

    Returns:
        A dictionary of settings key-value pairs.
    """
    settings: dict[str, Any] = {}
    if settings_elem is None:
        return settings

    for child in settings_elem:
        # Check if the child specifies a 'name' attribute (<Setting name="key">)
        key = child.attrib.get("name", child.tag)

        # Check if the value is specified as an attribute or as element text
        if "value" in child.attrib:
            val = child.attrib["value"].strip()
        else:
            val = (child.text or "").strip()

        settings[key] = val

    return settings


def _parse_action_element(action_elem: ET.Element) -> Action:
    """Parse a single action XML element into an Action model.

    This function recursively parses nested actions within <Then> and <Else>
    branches of Condition actions.

    Args:
        action_elem: The XML Element representing an action.

    Returns:
        A validated Action model.

    Raises:
        WorkflowParseError: If required attributes ('id', 'type', 'name')
            are missing.
    """
    # 1. Validate required 'id' attribute
    action_id = action_elem.attrib.get("id")
    if not action_id:
        raise WorkflowParseError(
            f"Action element <{action_elem.tag}> is missing required 'id' attribute."
        )

    # 2. Extract action type (from attribute 'type' or fallback to tag name)
    if action_elem.tag == "Action":
        raw_type = action_elem.attrib.get("type")
        if not raw_type:
            raise WorkflowParseError(
                f"Action '{action_id}' is missing required 'type' attribute."
            )
    else:
        # Tag itself might be the action type, e.g. <Loop id="act-1" ...>
        raw_type = action_elem.attrib.get("type", action_elem.tag)

    action_type = ActionType.from_string(raw_type)

    # 3. Validate required 'name' attribute
    action_name = action_elem.attrib.get("name")
    if not action_name:
        raise WorkflowParseError(
            f"Action '{action_id}' is missing required 'name' attribute."
        )

    # 4. Extract action settings dictionary
    settings = _parse_settings(action_elem.find("Settings"))

    # 5. Recursively parse nested Then and Else branches for Condition actions
    then_actions: list[Action] = []
    then_elem = action_elem.find("Then")
    if then_elem is not None:
        for child in then_elem:
            if child.tag == "Action" or "id" in child.attrib:
                then_actions.append(_parse_action_element(child))

    else_actions: list[Action] = []
    else_elem = action_elem.find("Else")
    if else_elem is not None:
        for child in else_elem:
            if child.tag == "Action" or "id" in child.attrib:
                else_actions.append(_parse_action_element(child))

    # 6. Capture raw XML snippet for logging and LLM fallback analysis
    try:
        raw_xml = ET.tostring(action_elem, encoding="unicode").strip()
    except Exception:
        raw_xml = None

    return Action(
        id=action_id,
        type=action_type,
        name=action_name,
        settings=settings,
        then_actions=then_actions,
        else_actions=else_actions,
        original_type=raw_type,
        raw_xml=raw_xml,
    )


def parse_workflow_from_string(xml_content: str, source_name: str = "<string>") -> Workflow:
    """Parse workflow XML content from a string into a Workflow model.

    Args:
        xml_content: The raw XML content as a string.
        source_name: A descriptive label for the source (used in error messages).

    Returns:
        A strongly typed Workflow model.

    Raises:
        WorkflowParseError: If the XML is malformed or missing required attributes.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        raise WorkflowParseError(
            f"Malformed XML in '{source_name}': {exc}"
        ) from exc

    # Ensure root element is <Workflow>
    if root.tag != "Workflow":
        raise WorkflowParseError(
            f"Expected root element <Workflow>, but found <{root.tag}> in '{source_name}'."
        )

    # Validate workflow name
    workflow_name = root.attrib.get("name")
    if not workflow_name:
        raise WorkflowParseError(
            f"Workflow root element in '{source_name}' is missing required 'name' attribute."
        )

    # Parse declared variables (<Variables> -> <Variable name="..." value="..." />)
    variables: list[Variable] = []
    variables_elem = root.find("Variables")
    if variables_elem is not None:
        for var_elem in variables_elem.findall("Variable"):
            var_name = var_elem.attrib.get("name")
            if not var_name:
                raise WorkflowParseError(
                    f"Variable in '{source_name}' is missing required 'name' attribute."
                )
            var_value = var_elem.attrib.get("value")
            if var_value is None:
                var_value = (var_elem.text or "").strip()
            variables.append(Variable(name=var_name, value=var_value))

    # Parse actions: look inside <Actions> container or root direct action children
    actions: list[Action] = []
    actions_elem = root.find("Actions")
    action_elements = actions_elem if actions_elem is not None else root

    for child in action_elements:
        # Ignore <Variables> or <Settings> elements at root level
        if child.tag in ("Variables", "Settings"):
            continue
        if child.tag == "Action" or "id" in child.attrib:
            actions.append(_parse_action_element(child))

    return Workflow(
        name=workflow_name,
        variables=variables,
        actions=actions,
    )


def parse_workflow(path: str | Path) -> Workflow:
    """Read an XML workflow file from disk and parse it into a Workflow model.

    Args:
        path: Filepath to the workflow XML file.

    Returns:
        A strongly typed Workflow model.

    Raises:
        FileNotFoundError: If the provided path does not exist.
        WorkflowParseError: If the XML file is malformed or invalid.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise WorkflowParseError(f"Could not read file '{file_path}': {exc}") from exc

    return parse_workflow_from_string(content, source_name=str(file_path))


def print_workflow_tree(workflow: Workflow) -> None:
    """Print a workflow and its nested actions as an indented tree in terminal.

    Args:
        workflow: The parsed Workflow object to display.
    """
    print(f"Workflow: {workflow.name}")

    if workflow.variables:
        print(f"Variables ({len(workflow.variables)}):")
        for var in workflow.variables:
            val_display = f"'{var.value}'" if var.value else "(empty)"
            print(f"  - {var.name} = {val_display}")

    print(f"Actions ({len(workflow.actions)} root action(s)):")
    for action in workflow.actions:
        _print_action_tree(action, indent=2)


def _print_action_tree(action: Action, indent: int = 2) -> None:
    """Recursively print an action and its nested branches.

    Uses ASCII connectors (+-, |--, \\--) for guaranteed cross-platform
    compatibility across all operating system encodings.

    Args:
        action: The Action object to print.
        indent: Indentation level in spaces.
    """
    indent_str = " " * indent
    settings_summary = ""
    if action.settings:
        formatted_items = [f"{k}={v!r}" for k, v in action.settings.items()]
        settings_summary = f" ({', '.join(formatted_items)})"

    print(
        f"{indent_str}+- [{action.id}] {action.type.value}: {action.name}{settings_summary}"
    )

    if action.then_actions:
        print(f"{indent_str}   |-- [THEN branch]:")
        for child in action.then_actions:
            _print_action_tree(child, indent=indent + 7)

    if action.else_actions:
        print(f"{indent_str}   \\-- [ELSE branch]:")
        for child in action.else_actions:
            _print_action_tree(child, indent=indent + 7)


def main() -> None:
    """CLI entrypoint for testing the workflow parser directly."""
    if len(sys.argv) < 2:
        print("Usage: python -m src.parser <path_to_workflow_xml>")
        print("Example: python -m src.parser samples/01_leave_approval.xml")
        sys.exit(1)

    target_path = sys.argv[1]
    try:
        wf = parse_workflow(target_path)
        print_workflow_tree(wf)
    except (FileNotFoundError, WorkflowParseError) as err:
        print(f"Error parsing workflow: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
