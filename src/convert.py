"""CLI workflow conversion script for Nintex-to-Power-Automate converter.

Usage:
    python -m src.convert samples/01_leave_approval.xml -o output/01.json
    python -m src.convert samples/04_unsupported_loop.xml -o output/04.json --use-llm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.generator import generate_flow_json
from src.mapper import map_workflow
from src.parser import WorkflowParseError, parse_workflow


def convert_workflow_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    use_llm: bool = False,
) -> int:
    """Parse a Nintex XML workflow, map to Power Automate, and generate output JSON.

    Args:
        input_path: Path to the input Nintex XML file.
        output_path: Optional path where the converted JSON will be written.
        use_llm: If True, invoke the LLM suggestion pipeline for unsupported actions.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    in_file = Path(input_path)
    if not in_file.exists():
        print(f"Error: Input file '{in_file}' not found.", file=sys.stderr)
        return 1

    try:
        # Step 1: Parse Nintex XML into typed domain models
        workflow = parse_workflow(in_file)

        # Step 2: Map to Power Automate schema using rule registry (with optional LLM)
        result = map_workflow(workflow, use_llm=use_llm)

        # Step 3: Serialize to Power Automate JSON format
        flow_json = generate_flow_json(result, indent=2)

        # Step 4: Write to output file if requested
        if output_path:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(flow_json, encoding="utf-8")

        # Step 5: Print conversion summary report
        review_status = "YES (Action required)" if result.unsupported else "No"
        print("=" * 60)
        print(f"Conversion Report: {result.flow_name}")
        print("=" * 60)
        print(f"Total Nintex Actions:   {result.total_actions}")
        print(f"Successfully Converted: {result.converted_count}")
        print(f"Coverage:               {result.coverage_percent}%")
        print(f"Manual Review Needed:   {review_status}")

        print(f"\nUnsupported Actions ({len(result.unsupported)}):")
        if result.unsupported:
            for item in result.unsupported:
                print(f"  - [{item.id}] {item.name} (Type: {item.original_type})")
                print(f"    Reason: {item.reason}")
        else:
            print("  (None)")

        if use_llm:
            print(
                f"\nLLM Suggestions ({len(result.llm_suggestions)}) [AI-suggested - needs human review]:"
            )
            if result.llm_suggestions:
                for s in result.llm_suggestions:
                    print(
                        f"  - [{s.action_id}] {s.action_name} (Original Type: {s.original_type})"
                    )
                    print(
                        f"    Suggested Action Type: {s.suggestion.suggested_action_type}"
                    )
                    print(f"    Confidence:            {s.confidence:.2f}")
                    print(f"    Reasoning:             {s.suggestion.reasoning}")
            else:
                print("  (None obtained)")

        print(f"\nWarnings ({len(result.warnings)}):")
        if result.warnings:
            for w in result.warnings:
                print(f"  - {w}")
        else:
            print("  (None)")

        if output_path:
            print(f"\nOutput written to: {output_path}")
        print("=" * 60)

        return 0

    except (WorkflowParseError, Exception) as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    """CLI entrypoint for running workflow conversions."""
    parser = argparse.ArgumentParser(
        description="Convert Nintex XML workflow exports to Power Automate flow definitions."
    )
    parser.add_argument(
        "xml_file",
        help="Path to the input Nintex workflow XML file",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path to write the converted Power Automate JSON file",
        default=None,
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Enable AI assistance (Groq LLM) to suggest translations for unsupported actions",
    )

    args = parser.parse_args()
    exit_code = convert_workflow_file(args.xml_file, args.output, use_llm=args.use_llm)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
