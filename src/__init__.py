"""Nintex-to-Power-Automate workflow converter package.

Phase 1: Project setup and XML parsing into typed models.
Phase 2: Rule-based mapping, expression conversion, and Power Automate JSON generation.
Phase 3: Schema-validated AI suggestions for unsupported workflow actions.
Phase 4: Evaluation benchmark harness and behavioural simulators.
"""

from src.expressions import convert_expression
from src.generator import generate_flow_dict, generate_flow_json
from src.llm import suggest_conversion
from src.llm_schema import ActionSuggestionItem, LLMSuggestion
from src.mapper import ConversionResult, UnsupportedAction, map_workflow
from src.models import Action, ActionType, Variable, Workflow
from src.simulate import SimulationTrace, simulate_nintex, simulate_power_automate

__all__ = [
    "Action",
    "ActionSuggestionItem",
    "ActionType",
    "ConversionResult",
    "LLMSuggestion",
    "SimulationTrace",
    "UnsupportedAction",
    "Variable",
    "Workflow",
    "convert_expression",
    "generate_flow_dict",
    "generate_flow_json",
    "map_workflow",
    "simulate_nintex",
    "simulate_power_automate",
    "suggest_conversion",
]
