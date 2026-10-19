"""Demonstration script connecting to the Nintex converter MCP server over stdio.

Starts the MCP server as a subprocess, initializes a client session,
lists the registered tools, calls convert_workflow on samples/01_leave_approval.xml,
and prints the resulting conversion summary report.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import anyio

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client


async def run_client_demo() -> None:
    """Connect to src.mcp_server over stdio, query tools, and run a conversion."""
    # Ensure current working directory is the project root
    project_root = Path(__file__).resolve().parent.parent

    # Prepare server subprocess launch parameters
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server"],
        cwd=str(project_root),
        env=os.environ.copy(),
    )

    sample_file = project_root / "samples" / "01_leave_approval.xml"
    if not sample_file.exists():
        print(f"Error: Sample file '{sample_file}' not found.", file=sys.stderr)
        return

    xml_content = sample_file.read_text(encoding="utf-8")

    print("=" * 65)
    print("Connecting to Nintex Converter MCP Server via stdio...")
    print("=" * 65)

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. Initialize MCP protocol handshake
            await session.initialize()
            print("[+] Successfully initialized MCP session.")

            # 2. List available tools
            tools_response = await session.list_tools()
            tool_names = [tool.name for tool in tools_response.tools]
            print(f"[+] Available MCP Tools ({len(tool_names)}):")
            for t in tools_response.tools:
                print(f"    - {t.name}: {t.description}")

            # 3. Call convert_workflow on sample 01
            print(f"\n[+] Calling 'convert_workflow' on '{sample_file.name}'...")
            call_result = await session.call_tool(
                "convert_workflow",
                arguments={"workflow_xml": xml_content, "use_llm": False},
            )

            # Extract response text content
            result_text = ""
            if call_result.content:
                for block in call_result.content:
                    if getattr(block, "type", "") == "text" or hasattr(block, "text"):
                        result_text += getattr(block, "text", "")

            if not result_text:
                print("[-] Received empty response from tool call.")
                return

            result_data = json.loads(result_text)

            # 4. Display Conversion Summary
            print("\n" + "=" * 65)
            print("MCP Conversion Result Summary")
            print("=" * 65)
            print(f"Success:                {result_data.get('success')}")
            print(f"Flow Name:              {result_data.get('name')}")
            metrics = result_data.get("metrics", {})
            print(f"Total Actions:          {metrics.get('total_actions')}")
            print(f"Converted Actions:      {metrics.get('converted_count')}")
            print(f"Coverage Percent:       {metrics.get('coverage_percent')}%")
            print(f"Needs Manual Review:    {result_data.get('needs_manual_review')}")
            print(f"Warnings:               {len(result_data.get('warnings', []))}")

            report = result_data.get("report", {})
            if report:
                print(f"Status:                 {report.get('manual_review_status')}")
            print("=" * 65)


def main() -> None:
    """Entry point running the asynchronous MCP client demo."""
    anyio.run(run_client_demo)


if __name__ == "__main__":
    main()
