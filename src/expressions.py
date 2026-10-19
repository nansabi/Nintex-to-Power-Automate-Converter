"""Expression converter for Nintex-style workflow references.

Converts Nintex variable and action references into Power Automate expressions:
  - {Variable:Name}        -> @variables('Name') [whole value]
                              @{variables('Name')} [inside text]
  - {Action:act-2.Outcome} -> @body('<PA_Name>')?['outcome'] [whole value]
                              @{body('<PA_Name>')?['outcome']} [inside text]

Unrecognized or malformed references are returned unchanged with warnings.
Note: Output expressions are a simplified subset; verify against Microsoft docs.
"""

from __future__ import annotations

import re

# Regex for matching {Prefix:Identifier} reference blocks
_REF_PATTERN = re.compile(r"\{([a-zA-Z0-9_\-]+):([^{}]+)\}")
_WHOLE_VAR_PATTERN = re.compile(r"^\{Variable:([a-zA-Z0-9_\- ]+)\}$")
_WHOLE_ACTION_PATTERN = re.compile(r"^\{Action:([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\}$")


def convert_expression(
    text: str,
    action_names: dict[str, str],
    valid_variables: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Convert Nintex-style references in a string to Power Automate expressions.

    Args:
        text: Input string potentially containing {Variable:...} or {Action:...}
            placeholders.
        action_names: Lookup dictionary mapping Nintex action IDs (e.g. 'act-2')
            to their sanitized Power Automate action names (e.g. 'Manager_Approval').
        valid_variables: Optional set of declared variable names. If provided,
            references to undeclared variables are flagged with warnings and preserved unchanged.

    Returns:
        A tuple of (converted_text, warnings). If a reference cannot be safely
        resolved, it is preserved verbatim in the text and a warning is appended.
    """
    if not isinstance(text, str) or not text:
        return text, []

    stripped = text.strip()
    warnings: list[str] = []

    # Case 1: Whole-value Variable reference -> @variables('Name')
    # Verify against Microsoft docs: workflow definition language variables() function
    var_match = _WHOLE_VAR_PATTERN.match(stripped)
    if var_match:
        var_name = var_match.group(1).strip()
        if valid_variables is not None and var_name not in valid_variables:
            warning = f"Referenced variable '{var_name}' is not declared in workflow variables."
            return text, [warning]
        return f"@variables('{var_name}')", []

    # Case 2: Whole-value Action property reference -> @body('PA_Name')?['property']
    # Verify against Microsoft docs: workflow definition language body() action outputs
    action_match = _WHOLE_ACTION_PATTERN.match(stripped)
    if action_match:
        action_id = action_match.group(1).strip()
        prop_name = action_match.group(2).strip().lower()
        if action_id in action_names:
            pa_name = action_names[action_id]
            return f"@body('{pa_name}')?['{prop_name}']", []
        else:
            warning = (
                f"Unknown action ID '{action_id}' in reference '{stripped}': "
                f"action not found in converted action mapping."
            )
            return text, [warning]

    # Case 3: Embedded references inside text -> replace with @{...} interpolation
    def _replace_reference(match: re.Match[str]) -> str:
        ref_type = match.group(1).strip()
        ref_payload = match.group(2).strip()
        full_token = match.group(0)

        if ref_type == "Variable":
            if valid_variables is not None and ref_payload not in valid_variables:
                warnings.append(
                    f"Referenced variable '{ref_payload}' in '{full_token}' is not declared in workflow variables."
                )
                return full_token
            # In-text variable replacement: @{variables('Name')}
            # Verify against Microsoft docs: string interpolation syntax @{...}
            return f"@{{variables('{ref_payload}')}}"

        if ref_type == "Action":
            # Action reference format: act-id.Property
            if "." in ref_payload:
                action_id, prop = ref_payload.split(".", 1)
                action_id = action_id.strip()
                prop_lower = prop.strip().lower()
                if action_id in action_names:
                    pa_name = action_names[action_id]
                    # In-text action output replacement: @{body('Name')?['prop']}
                    return f"@{{body('{pa_name}')?['{prop_lower}']}}"
                else:
                    warnings.append(
                        f"Unknown action ID '{action_id}' in reference '{full_token}'."
                    )
                    return full_token
            else:
                warnings.append(
                    f"Malformed action reference '{full_token}': expected 'id.property'."
                )
                return full_token

        # Unrecognized reference type (e.g. {Custom:...})
        warnings.append(
            f"Unrecognized reference type '{ref_type}' in token '{full_token}'."
        )
        return full_token

    converted = _REF_PATTERN.sub(_replace_reference, text)
    return converted, warnings
