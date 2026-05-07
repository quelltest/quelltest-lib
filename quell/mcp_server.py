"""
Quell MCP Server — exposes Quell's engine to AI coding agents.

AI agents (Claude Code, Cursor, Devin) can call these tools to verify
tests they generate before committing, without any manual steps.

Run:
    uvx quell-mcp
    python -m quell.mcp_server

Requires:
    pip install quell[mcp]   # installs mcp>=1.0.0

Tools exposed:
    verify_test          — verify a test kills mutations in a source file
    get_survivors        — list surviving mutants for a file
    generate_killing_test — generate a verified killing test for a mutant
    get_quell_score      — get current mutation score
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path


def main() -> None:
    """Entry point for the quell-mcp CLI command."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError:
        print(
            "Error: mcp package is required.\n"
            "Install it with: pip install quell[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(_run_server())


async def _run_server() -> None:
    """Start the MCP server and serve over stdio."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    server = Server("quell")
    _register_tools(server)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _register_tools(server: "Server") -> None:
    """Register all Quell MCP tools on the server."""
    from mcp.server import Server

    @server.tool()
    async def verify_test(test_code: str, source_file: str) -> dict:
        """
        Verify that a test actually kills mutations in the source file.

        The test must pass on original code and fail when a mutant is applied.
        Use this after generating a test to confirm it catches real bugs.

        Returns:
            {verified: bool, kills_mutants: int, score_delta: float, explanation: str}
        """
        from quell.sdk import Quell

        q = Quell(project_root=Path("."))
        result = q.verify_test(test_code=test_code, source_file=source_file)
        return {
            "verified": result.verified,
            "kills_mutants": result.kills_mutants,
            "score_delta": result.score_delta,
            "explanation": result.explanation,
            "status": result.status,
        }

    @server.tool()
    async def get_survivors(source_file: str) -> list[dict]:
        """
        Get all surviving mutants for a source file.

        Returns a list of mutants that your tests are not killing.
        Each mutant describes the exact code change that slipped through.
        """
        from quell.adapters.mutmut_adapter import MutmutAdapter
        from quell.core.analyzer import MutationAnalyzer

        adapter = MutmutAdapter(Path("."))
        analyzer = MutationAnalyzer()
        survivors = adapter.read_survivors()
        survivors = [analyzer.analyze(m) for m in survivors]

        target = Path(source_file).resolve()
        file_survivors = [
            m for m in survivors
            if m.file_path.resolve() == target
        ]

        return [
            {
                "id": m.id,
                "file": str(m.file_path),
                "line": m.line_start,
                "operator": m.operator.value,
                "original": m.original_code.strip(),
                "mutated": m.mutated_code.strip(),
                "function": m.function_name,
            }
            for m in file_survivors
        ]

    @server.tool()
    async def generate_killing_test(mutant_id: str, source_file: str) -> dict:
        """
        Generate a verified killing test for a specific mutant.

        The returned test has been verified to kill the mutant and pass
        on the original code. It is ready to be written to the test file.

        Returns:
            {test_code: str, test_function_name: str, verified: bool, explanation: str}
        """
        from quell.adapters.mutmut_adapter import MutmutAdapter
        from quell.core.analyzer import MutationAnalyzer
        from quell.core.generator import TestGenerator
        from quell.core.verifier import MutantVerifier
        from quell.core.models import QuellConfig, VerificationStatus
        from quell.llm.client import LLMClient

        config = QuellConfig()
        llm = LLMClient.from_config(config)
        generator = TestGenerator(llm, config)
        verifier = MutantVerifier(config)
        analyzer = MutationAnalyzer()

        adapter = MutmutAdapter(Path("."))
        survivors = adapter.read_survivors()
        survivors = [analyzer.analyze(m) for m in survivors]

        target = next((m for m in survivors if m.id == mutant_id), None)
        if target is None:
            return {
                "test_code": "",
                "test_function_name": "",
                "verified": False,
                "explanation": f"Mutant {mutant_id} not found in survivors.",
            }

        generated = await generator.generate(target)
        for _ in range(config.max_verification_attempts):
            vr = verifier.verify(target, generated)
            if vr.status == VerificationStatus.VERIFIED:
                return {
                    "test_code": generated.test_code,
                    "test_function_name": generated.test_function_name,
                    "verified": True,
                    "explanation": generated.explanation,
                }
            generated = await generator.generate(target)

        return {
            "test_code": generated.test_code,
            "test_function_name": generated.test_function_name,
            "verified": False,
            "explanation": f"Could not generate a verified killing test after {config.max_verification_attempts} attempts.",
        }

    @server.tool()
    async def get_quell_score(file_path: str | None = None) -> dict:
        """
        Get current mutation score.

        Args:
            file_path: Optional file path to get score for a single file.
                       If None, returns the project-wide score.

        Returns:
            {total: float, percentage: int, grade: str, by_file: dict}
        """
        from quell.sdk import Quell

        q = Quell(project_root=Path("."))
        score = q.get_score(path=file_path)

        grade = "A" if score.total >= 0.80 else "B" if score.total >= 0.60 else "C" if score.total >= 0.40 else "F"

        return {
            "total": score.total,
            "percentage": score.percentage,
            "grade": grade,
            "by_file": score.by_file,
            "total_mutants": score.total_mutants,
            "killed_mutants": score.killed_mutants,
            "survived_mutants": score.survived_mutants,
        }


if __name__ == "__main__":
    main()
