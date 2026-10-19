"""Evaluation harness and fidelity benchmark for Nintex-to-Power-Automate conversions.

Computes comprehensive fidelity scores comparing generated flows against golden definitions:
  - Structure Score: Validates trigger presence, action counts, types, and sequence.
  - Expression Score: Compares parameter expressions and variable mappings against ground truth.
  - Behaviour Score: Executes simulation traces to confirm runtime parity.
  - Overall Fidelity Score: Composite metric measuring total conversion quality.

Outputs results to:
  - evals/results/latest.md (Markdown report)
  - evals/results/latest.json (Machine-readable JSON)
  - evals/results/llm_latest.md (Optional LLM evaluation metrics)
  - evals/results/llm_latest.json (Machine-readable LLM evaluation metrics)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from src.generator import generate_flow_dict
from src.llm import get_default_client, suggest_conversion
from src.llm_schema import LLMSuggestion
from src.mapper import map_workflow
from src.models import Action, ActionType, Workflow
from src.parser import parse_workflow
from src.simulate import simulate_nintex, simulate_power_automate

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BASE_DIR / "samples"
GOLDEN_DIR = BASE_DIR / "evals" / "golden"
RESULTS_DIR = BASE_DIR / "evals" / "results"
HANDWRITTEN_FILE = BASE_DIR / "evals" / "expected_handwritten.json"

# verified against Microsoft Learn: Until runs until its condition is true
ALLOWED_LLM_TYPES: dict[str, list[str]] = {
    "Loop": ["Until", "Foreach"],
    "WebServiceCall": ["Http"],
}



def _extract_action_types_in_order(actions_dict: dict[str, Any]) -> list[str]:
    """Recursively extract Power Automate action types preserving sequence."""
    types: list[str] = []
    for act in actions_dict.values():
        if isinstance(act, dict):
            t = act.get("type")
            if t:
                types.append(t)
            # Recurse into nested condition branches
            if "actions" in act and isinstance(act["actions"], dict):
                types.extend(_extract_action_types_in_order(act["actions"]))
            if "else" in act and isinstance(act["else"], dict):
                else_acts = act["else"].get("actions", {})
                if isinstance(else_acts, dict):
                    types.extend(_extract_action_types_in_order(else_acts))
    return types


def compute_structure_score(
    actual: dict[str, Any],
    golden: dict[str, Any],
    expected_types: list[str] | None = None,
) -> float:
    """Compare structural fidelity (trigger and action types) against reference."""
    score = 0.0

    # 1. Trigger comparison (20 pts)
    act_triggers = actual.get("definition", {}).get("triggers", {})
    gold_triggers = golden.get("definition", {}).get("triggers", {}) if golden else {}
    if act_triggers and (not gold_triggers or act_triggers.keys() == gold_triggers.keys()):
        score += 20.0
    elif not act_triggers and not gold_triggers:
        score += 20.0

    # 2. Actions count and types comparison (80 pts)
    act_actions = actual.get("definition", {}).get("actions", {})

    if expected_types is not None:
        actual_types = _extract_action_types_in_order(act_actions)
        if not expected_types and not actual_types:
            return 100.0
        total_exp = len(expected_types)
        matched = 0
        for i in range(min(len(actual_types), total_exp)):
            if actual_types[i] == expected_types[i]:
                matched += 1
        types_ratio = matched / total_exp if total_exp > 0 else 1.0
        score += types_ratio * 80.0
        return round(score, 1)

    gold_actions = golden.get("definition", {}).get("actions", {}) if golden else {}

    if not gold_actions and not act_actions:
        return 100.0

    total_golden = len(gold_actions)
    matched = 0
    for name, gold_def in gold_actions.items():
        if name in act_actions:
            if act_actions[name].get("type") == gold_def.get("type"):
                matched += 1

    actions_ratio = matched / total_golden if total_golden > 0 else 1.0
    score += actions_ratio * 80.0

    return round(score, 1)


def _extract_expressions(obj: Any) -> list[str]:
    """Recursively extract expression strings starting with @ or containing @{...}."""
    expressions: list[str] = []
    if isinstance(obj, str):
        if obj.startswith("@") or "@{" in obj:
            expressions.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            expressions.extend(_extract_expressions(v))
    elif isinstance(obj, list):
        for item in obj:
            expressions.extend(_extract_expressions(item))
    return expressions


def compute_expression_score(
    actual: dict[str, Any],
    golden: dict[str, Any],
    expected_expressions: list[str] | None = None,
) -> float:
    """Compare expression translation accuracy against reference."""
    act_exprs = _extract_expressions(actual.get("definition", {}).get("actions", {}))

    if expected_expressions is not None:
        if not expected_expressions and not act_exprs:
            return 100.0
        if not expected_expressions:
            return 100.0
        # Check matched against exact handwritten expression strings
        matched = sum(1 for e in expected_expressions if e in act_exprs)
        return round((matched / len(expected_expressions)) * 100.0, 1)

    gold_exprs = _extract_expressions(golden.get("definition", {}).get("actions", {})) if golden else []

    if not gold_exprs and not act_exprs:
        return 100.0

    if not gold_exprs:
        return 100.0

    matched = sum(1 for e in gold_exprs if e in act_exprs)
    return round((matched / len(gold_exprs)) * 100.0, 1)


def compute_behaviour_score(sample_stem: str, wf: Workflow, actual_dict: dict[str, Any]) -> float:
    """Run simulation scenarios for executable workflows and measure trace parity."""
    scenarios: list[dict[str, Any]] = [{}]

    if "01" in sample_stem or "leave_approval" in sample_stem:
        scenarios = [{"approval_outcome": "Approved"}, {"approval_outcome": "Rejected"}]
    elif "05" in sample_stem or "nested_conditions" in sample_stem:
        scenarios = [
            {"approval_outcome": "Approved", "RequestPriority": "High"},
            {"approval_outcome": "Approved", "RequestPriority": "Low"},
            {"approval_outcome": "Rejected"},
        ]

    passed = 0
    for sc in scenarios:
        try:
            trace_nintex = simulate_nintex(wf, sc)
            trace_pa = simulate_power_automate(actual_dict, sc)
            if trace_nintex.emails_sent == trace_pa.emails_sent:
                passed += 1
        except Exception:
            pass

    return round((passed / len(scenarios)) * 100.0, 1) if scenarios else 100.0


def evaluate_sample(
    sample_file: Path,
    golden_dir: Path,
    handwritten_benchmarks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a single sample workflow and compute all fidelity metrics."""
    stem = sample_file.stem
    wf = parse_workflow(sample_file)
    result = map_workflow(wf, use_llm=False)
    actual_dict = generate_flow_dict(result)

    golden_file = golden_dir / f"{stem}.expected.json"
    golden_dict: dict[str, Any] = {}
    if golden_file.exists():
        golden_dict = json.loads(golden_file.read_text(encoding="utf-8"))
    elif handwritten_benchmarks is None or stem not in handwritten_benchmarks:
        raise FileNotFoundError(f"Missing expected golden file: {golden_file}")

    exp_types = None
    exp_exprs = None
    if handwritten_benchmarks and stem in handwritten_benchmarks:
        hw = handwritten_benchmarks[stem]
        exp_types = hw.get("action_types")
        exp_exprs = hw.get("expressions")

    struct_score = compute_structure_score(actual_dict, golden_dict, expected_types=exp_types)
    expr_score = compute_expression_score(actual_dict, golden_dict, expected_expressions=exp_exprs)
    behav_score = compute_behaviour_score(stem, wf, actual_dict)

    # Universal overall fidelity formula:
    # 25% structure + 25% expression + 30% behaviour + 20% coverage - (5 * warnings_count)
    base_fidelity = (
        0.25 * struct_score
        + 0.25 * expr_score
        + 0.30 * behav_score
        + 0.20 * result.coverage_percent
    )
    penalty = 5.0 * len(result.warnings)
    overall_score = max(0.0, round(base_fidelity - penalty, 1))

    is_supported = len(result.unsupported) == 0

    return {
        "sample": stem,
        "workflow_name": wf.name,
        "is_supported": is_supported,
        "structure_score": struct_score,
        "expression_score": expr_score,
        "behaviour_score": behav_score,
        "coverage_percent": result.coverage_percent,
        "unsupported_count": len(result.unsupported),
        "warnings_count": len(result.warnings),
        "overall_fidelity": overall_score,
    }


def _extract_unsupported_actions_from_sample(sample_path: Path) -> list[Action]:
    """Parse a sample and extract actions that map to UNKNOWN or unsupported."""
    wf = parse_workflow(sample_path)
    res = map_workflow(wf, use_llm=False)
    unsupported_ids = {u.id for u in res.unsupported}
    return [act for act in wf.actions if act.id in unsupported_ids]


def _call_suggest_with_tracking(
    action: Action,
    client: Any,
    max_retries: int = 2,
) -> tuple[LLMSuggestion | None, bool, int, str | None]:
    """Execute suggest_conversion while tracking first-try validity, retries, and errors."""
    from src.llm import USER_PROMPT_TEMPLATE, SYSTEM_PROMPT, get_default_client

    if client is None:
        default_client, default_model = get_default_client()
        if default_client is None:
            return None, False, 0, "No client or GROQ_API_KEY available"
        active_client = default_client
        active_model = default_model
    else:
        active_client = client
        active_model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    orig_type = action.original_type or action.type.value
    raw_xml_data = action.raw_xml or f"<Action id='{action.id}' type='{orig_type}' name='{action.name}' />"
    user_content = USER_PROMPT_TEMPLATE.format(
        action_id=action.id,
        action_name=action.name,
        original_type=orig_type,
        raw_xml=raw_xml_data,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    retries_needed = 0
    first_try_valid = False
    last_err: str | None = None

    for attempt in range(max_retries + 1):
        try:
            response = active_client.chat.completions.create(
                model=active_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_text = response.choices[0].message.content or ""
            suggestion = LLMSuggestion.model_validate_json(raw_text)
            if attempt == 0:
                first_try_valid = True
            return suggestion, first_try_valid, retries_needed, None
        except (json.JSONDecodeError, Exception) as err:
            last_err = f"{type(err).__name__}: {err}"
            if attempt < max_retries:
                retries_needed += 1
                messages.append({"role": "assistant", "content": str(locals().get("raw_text", ""))})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous output failed validation: {err}. "
                            "Please fix the error and return ONLY a valid JSON object matching the LLMSuggestion schema."
                        ),
                    }
                )
            else:
                return None, False, retries_needed, last_err

    return None, False, retries_needed, last_err


def run_llm_eval(
    live: bool = False,
    fake_client: Any = None,
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    """Evaluate LLM suggestion capabilities on unsupported action samples."""
    s_dir = samples_dir or SAMPLES_DIR

    test_actions: list[Action] = []
    sample_files = [s_dir / "04_unsupported_loop.xml", s_dir / "08_multiple_unsupported.xml"]
    for sf in sample_files:
        if sf.exists():
            test_actions.extend(_extract_unsupported_actions_from_sample(sf))

    if not test_actions:
        test_actions = [
            Action(
                id="act-2",
                type=ActionType.UNKNOWN,
                name="Process Records",
                original_type="Loop",
                raw_xml="<Action id='act-2' type='Loop' name='Process Records' />",
            ),
            Action(
                id="act-4",
                type=ActionType.UNKNOWN,
                name="Call Legacy API",
                original_type="WebServiceCall",
                raw_xml="<Action id='act-4' type='WebServiceCall' name='Call Legacy API' />",
            ),
        ]

    results: list[dict[str, Any]] = []

    client = fake_client if not live else None
    if live and client is None:
        def_client, _ = get_default_client()
        client = def_client

    for action in test_actions:
        orig = action.original_type or "Loop"
        allowed = ALLOWED_LLM_TYPES.get(orig, [])

        suggestion, first_try_valid, retries_needed, error_msg = _call_suggest_with_tracking(
            action, client=client
        )

        is_valid = suggestion is not None
        matched_allowed = False
        conf = 0.0
        suggested_type = "None"

        if suggestion:
            suggested_type = suggestion.suggested_action_type
            matched_allowed = any(
                suggested_type.strip().lower() == a.strip().lower()
                for a in allowed
            )
            conf = suggestion.confidence

        results.append(
            {
                "action_id": action.id,
                "action_name": action.name,
                "original_type": orig,
                "suggested_type": suggested_type,
                "first_try_valid": first_try_valid,
                "retries_needed": retries_needed,
                "matched_allowed": matched_allowed,
                "confidence": conf,
                "schema_valid": is_valid,
                "error": error_msg,
                "logic_check": "manual review needed" if orig == "Loop" else "-",
            }
        )

    mean_conf = round(sum(r["confidence"] for r in results) / len(results), 2) if results else 0.0
    valid_rate = round(sum(1 for r in results if r["schema_valid"]) / len(results) * 100.0, 1) if results else 0.0
    type_correct_count = sum(1 for r in results if r["matched_allowed"])
    type_correct_total = len(results)
    type_correct_rate = round((type_correct_count / type_correct_total * 100.0), 1) if type_correct_total else 0.0

    return {
        "status": "LIVE" if live else "OFFLINE (Mock/Skipped)",
        "items": results,
        "type_correct_count": type_correct_count,
        "type_correct_total": type_correct_total,
        "type_correct_rate": type_correct_rate,
        "mean_confidence": mean_conf,
        "schema_valid_rate": valid_rate,
    }


def format_markdown_table(eval_records: list[dict[str, Any]]) -> str:
    """Format evaluation records as a clean markdown table."""
    headers = [
        "Sample",
        "Structure",
        "Expression",
        "Behaviour",
        "Coverage",
        "Unsup.",
        "Warn.",
        "Fidelity",
    ]
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {':--- | ' * (len(headers) - 1)}:--- |",
    ]

    for r in eval_records:
        lines.append(
            f"| `{r['sample']}` | {r['structure_score']}% | {r['expression_score']}% | "
            f"{r['behaviour_score']}% | {r['coverage_percent']}% | {r['unsupported_count']} | "
            f"{r['warnings_count']} | **{r['overall_fidelity']}%** |"
        )

    return "\n".join(lines)


def format_llm_markdown_table(items: list[dict[str, Any]]) -> str:
    """Format LLM benchmark results as a clean markdown table."""
    headers = [
        "Action ID",
        "Original Type",
        "Suggested PA Type",
        "First Try Valid",
        "Retries",
        "Allowed Match",
        "Confidence",
        "Logic check",
        "Status / Error",
    ]
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {':--- | ' * (len(headers) - 1)}:--- |",
    ]
    for it in items:
        first_try_str = "✅ Yes" if it["first_try_valid"] else "❌ No"
        matched_str = "✅ Yes" if it["matched_allowed"] else "❌ No"
        if not it["schema_valid"]:
            status_str = f"❌ Failed: {it['error']}" if it["error"] else "❌ Failed"
        elif not it["matched_allowed"]:
            status_str = "wrong action type"
        else:
            status_str = "OK"
        logic_check_str = it.get("logic_check", "-")
        lines.append(
            f"| `{it['action_id']}` | `{it['original_type']}` | `{it['suggested_type']}` | "
            f"{first_try_str} | {it['retries_needed']} | {matched_str} | {it['confidence']} | {logic_check_str} | {status_str} |"
        )
    return "\n".join(lines)



def run_all_evals(
    threshold: float = 95.0,
    live: bool = False,
    fake_client: Any = None,
    samples_dir: Path | None = None,
    golden_dir: Path | None = None,
    results_dir: Path | None = None,
    handwritten_file: Path | None = None,
) -> int:
    """Execute complete evaluation suite, save reports, and enforce score threshold."""
    s_dir = samples_dir or SAMPLES_DIR
    g_dir = golden_dir or GOLDEN_DIR
    r_dir = results_dir or RESULTS_DIR
    hw_file = handwritten_file or HANDWRITTEN_FILE
    r_dir.mkdir(parents=True, exist_ok=True)

    handwritten_benchmarks = None
    if hw_file.exists():
        handwritten_benchmarks = json.loads(hw_file.read_text(encoding="utf-8"))

    records: list[dict[str, Any]] = []
    sample_files = sorted(s_dir.glob("*.xml"))

    for sf in sample_files:
        rec = evaluate_sample(sf, g_dir, handwritten_benchmarks=handwritten_benchmarks)
        records.append(rec)

    # Format and save JSON
    json_path = r_dir / "latest.json"
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    # Format and save Markdown report
    md_content = [
        "# 📈 Evaluation & Fidelity Benchmark Report",
        "",
        "## Overall Conversion Fidelity",
        format_markdown_table(records),
        "",
        "### 🧮 Scoring Formula",
        "- **Overall Fidelity** = `0.25 * Structure + 0.25 * Expression + 0.30 * Behaviour + 0.20 * Coverage - (5 * Warnings)`",
        "- **Structure Score**: Validates trigger and action types sequence against reference.",
        "- **Expression Score**: Matches parameter expression conversions against ground truth.",
        "- **Behaviour Score**: Verifies simulation traces match across Nintex and Power Automate execution.",
        "- **Coverage %**: Percentage of workflow actions mapped without fallback.",
        "- **Warning Penalty**: Each warning reduces fidelity score by 5 points.",
        "",
    ]
    md_path = r_dir / "latest.md"
    md_path.write_text("\n".join(md_content), encoding="utf-8")

    # Print summary table to stdout
    print("=" * 80)
    print("EVALUATION FIDELITY REPORT")
    print("=" * 80)
    print(format_markdown_table(records))
    print("=" * 80)
    print(f"Results written to: {md_path} and {json_path}")

    # LLM Eval logic:
    if not live and fake_client is None:
        print("\nLLM eval skipped (use --live)")
    else:
        llm_report = run_llm_eval(live=live, fake_client=fake_client, samples_dir=s_dir)
        llm_json_path = r_dir / "llm_latest.json"
        llm_json_path.write_text(json.dumps(llm_report, indent=2), encoding="utf-8")

        tc_count = llm_report["type_correct_count"]
        tc_total = llm_report["type_correct_total"]
        tc_rate = llm_report["type_correct_rate"]
        schema_rate = llm_report["schema_valid_rate"]

        llm_md_content = [
            "# 🤖 LLM Suggestion Benchmark Report",
            f"**Mode:** {llm_report['status']}",
            f"**Type-correct:** {tc_count}/{tc_total} ({tc_rate}%)",
            f"**Schema-valid Rate:** {schema_rate}%",
            f"**Mean Confidence:** {llm_report['mean_confidence']}",
            "",
            format_llm_markdown_table(llm_report["items"]),
            "",
        ]
        llm_md_path = r_dir / "llm_latest.md"
        llm_md_path.write_text("\n".join(llm_md_content), encoding="utf-8")

        print("\n" + "=" * 80)
        print("LLM SUGGESTION BENCHMARK REPORT")
        print("=" * 80)
        print(f"Mode: {llm_report['status']}")
        print(f"Type-correct: {tc_count}/{tc_total} ({tc_rate}%)  [Schema-valid Rate: {schema_rate}% | Mean Confidence: {llm_report['mean_confidence']}]")
        print(format_llm_markdown_table(llm_report["items"]))
        print(f"LLM Results written to: {llm_md_path} and {llm_json_path}")
        print("=" * 80)

    # Check threshold for supported samples (01, 02, 03, 05, 06)
    failures: list[str] = []
    for r in records:
        if r["is_supported"] and r["overall_fidelity"] < threshold:
            failures.append(f"{r['sample']} scored {r['overall_fidelity']}% (< {threshold}%)")

    if failures:
        print("\n[FAIL] EVALUATION FAILED (Threshold violations):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\n[PASS] All supported samples passed the fidelity threshold (>= {threshold}%).")
    return 0


def main() -> None:
    """CLI entrypoint for running evals."""
    parser = argparse.ArgumentParser(
        description="Run evaluation harness and fidelity benchmarks for Nintex-to-Power-Automate conversions."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=95.0,
        help="Minimum overall fidelity score required for supported workflows (default: 95.0)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Run live LLM evaluation using real Groq API key from .env (skipped by default)",
    )

    args = parser.parse_args()
    exit_code = run_all_evals(threshold=args.threshold, live=args.live)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
