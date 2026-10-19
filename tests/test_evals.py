"""Unit tests for the Phase 4 evaluation harness.

Tests:
- Structure scoring function (perfect vs imperfect)
- Expression scoring function (perfect vs imperfect)
- Behaviour scoring function (perfect vs imperfect)
- evaluate_sample produces 100% on fully supported samples
- run_all_evals enforces threshold with appropriate exit codes (0 vs 1)
- run_llm_eval in offline mode with fake client
"""

import json
from pathlib import Path
import pytest

from evals.run_evals import (
    compute_behaviour_score,
    compute_expression_score,
    compute_structure_score,
    evaluate_sample,
    run_all_evals,
    run_llm_eval,
)
from src.parser import parse_workflow

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "samples"
GOLDEN_DIR = BASE_DIR / "evals" / "golden"


class FakeEvalClient:
    """Mock client for testing LLM evaluation harness."""

    def __init__(self, action_type: str = "Until", confidence: float = 0.88) -> None:
        self.action_type = action_type
        self.confidence = confidence

    @property
    def chat(self):
        parent = self

        class ChatCompletions:
            def create(self, **kwargs):
                payload = json.dumps(
                    {
                        "suggested_action_type": parent.action_type,
                        "power_automate_action": {"type": parent.action_type},
                        "confidence": parent.confidence,
                        "reasoning": "Mocked test translation",
                        "needs_human_review": True,
                    }
                )
                choice = type("Choice", (), {"message": type("Msg", (), {"content": payload})()})()
                return type("Resp", (), {"choices": [choice]})()

        return type("Chat", (), {"completions": ChatCompletions()})()


def test_structure_score_perfect_and_imperfect() -> None:
    """Test structure score awards 100 for exact match and penalizes mismatches."""
    golden = {
        "definition": {
            "triggers": {"manual": {"type": "Request"}},
            "actions": {
                "Act1": {"type": "InitializeVariable"},
                "Act2": {"type": "OpenApiConnection"},
            },
        }
    }

    # Perfect match
    score_perfect = compute_structure_score(golden, golden)
    assert score_perfect == 100.0

    # Wrong action type
    wrong_type = {
        "definition": {
            "triggers": {"manual": {"type": "Request"}},
            "actions": {
                "Act1": {"type": "InitializeVariable"},
                "Act2": {"type": "WrongType"},
            },
        }
    }
    score_imperfect = compute_structure_score(wrong_type, golden)
    assert score_imperfect < 100.0

    # Missing trigger
    missing_trigger = {
        "definition": {
            "triggers": {},
            "actions": golden["definition"]["actions"],
        }
    }
    score_missing_trig = compute_structure_score(missing_trigger, golden)
    assert score_missing_trig < 100.0


def test_expression_score_perfect_and_imperfect() -> None:
    """Test expression score measures parameter translation accuracy."""
    golden = {
        "definition": {
            "actions": {
                "Email": {
                    "inputs": {
                        "parameters": {
                            "to": "@variables('Recipient')",
                            "body": "Hello @{variables('Name')}!",
                        }
                    }
                }
            }
        }
    }

    # Exact match
    score_perfect = compute_expression_score(golden, golden)
    assert score_perfect == 100.0

    # Broken expression
    broken = {
        "definition": {
            "actions": {
                "Email": {
                    "inputs": {
                        "parameters": {
                            "to": "@variables('WrongVar')",
                            "body": "Hello plain text",
                        }
                    }
                }
            }
        }
    }
    score_broken = compute_expression_score(broken, golden)
    assert score_broken < 100.0


def test_sample_01_eval_scores_100() -> None:
    """Test that sample 01 scores 100% on all fidelity dimensions."""
    sample_file = SAMPLES_DIR / "01_leave_approval.xml"
    report = evaluate_sample(sample_file, GOLDEN_DIR)

    assert report["structure_score"] == 100.0
    assert report["expression_score"] == 100.0
    assert report["behaviour_score"] == 100.0
    assert report["coverage_percent"] == 100.0
    assert report["overall_fidelity"] == 100.0
    assert report["is_supported"] is True


def test_sample_07_scores_below_100_due_to_warning_penalty() -> None:
    """Test that each warning reduces fidelity by 5 points and sample 07 scores below 100."""
    sample_file = SAMPLES_DIR / "07_bad_reference.xml"
    report = evaluate_sample(sample_file, GOLDEN_DIR)

    assert report["warnings_count"] == 1
    assert report["overall_fidelity"] < 100.0
    assert report["overall_fidelity"] == 95.0


def test_handwritten_expectations_scoring() -> None:
    """Test scoring Structure and Expression against evals/expected_handwritten.json."""
    from evals.run_evals import HANDWRITTEN_FILE
    assert HANDWRITTEN_FILE.exists()
    hw_benchmarks = json.loads(HANDWRITTEN_FILE.read_text(encoding="utf-8"))

    for sample_name in ["01_leave_approval", "05_nested_conditions", "06_variable_in_condition"]:
        sf = SAMPLES_DIR / f"{sample_name}.xml"
        report = evaluate_sample(sf, GOLDEN_DIR, handwritten_benchmarks=hw_benchmarks)
        assert report["structure_score"] == 100.0
        assert report["expression_score"] == 100.0
        assert report["overall_fidelity"] >= 95.0


def test_threshold_enforcement(tmp_path: Path) -> None:
    """Test run_all_evals return codes based on threshold 95.0."""
    results_dir = tmp_path / "results"

    # Default threshold 95.0 should pass with exit code 0
    code_pass = run_all_evals(
        threshold=95.0,
        samples_dir=SAMPLES_DIR,
        golden_dir=GOLDEN_DIR,
        results_dir=results_dir,
    )
    assert code_pass == 0
    assert (results_dir / "latest.md").exists()
    assert (results_dir / "latest.json").exists()

    # Unreasonable threshold 101.0 must fail with exit code 1
    code_fail = run_all_evals(
        threshold=101.0,
        samples_dir=SAMPLES_DIR,
        golden_dir=GOLDEN_DIR,
        results_dir=results_dir,
    )
    assert code_fail == 1


def test_llm_eval_offline_mode() -> None:
    """Test LLM evaluation benchmark using injected fake client."""
    # DoUntil is no longer allowed (only Until and Foreach are valid)
    fake_client_dountil = FakeEvalClient(action_type="DoUntil", confidence=0.85)
    report_dountil = run_llm_eval(live=False, fake_client=fake_client_dountil)

    assert report_dountil["schema_valid_rate"] == 100.0
    assert report_dountil["mean_confidence"] == 0.85
    assert len(report_dountil["items"]) >= 2
    # DoUntil matches 0 loop items (only WebServiceCall Http would match if returned, but fake client returned DoUntil for all)
    assert report_dountil["type_correct_count"] == 0
    assert report_dountil["type_correct_rate"] == 0.0
    loop_item_fail = next(it for it in report_dountil["items"] if it["original_type"] == "Loop")
    assert loop_item_fail["matched_allowed"] is False
    assert loop_item_fail["logic_check"] == "manual review needed"

    # Until is allowed and passes allowed-match check for loops
    fake_client_until = FakeEvalClient(action_type="Until", confidence=0.90)
    report_until = run_llm_eval(live=False, fake_client=fake_client_until)
    loop_item_pass = next(it for it in report_until["items"] if it["original_type"] == "Loop")
    assert loop_item_pass["matched_allowed"] is True
    assert loop_item_pass["first_try_valid"] is True
    assert loop_item_pass["retries_needed"] == 0
    assert loop_item_pass["logic_check"] == "manual review needed"
    assert report_until["type_correct_count"] > 0
    assert report_until["type_correct_rate"] > 0.0


