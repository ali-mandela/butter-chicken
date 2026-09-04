from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from aivar.compiler import compile_test
from aivar.executor import run_test
from aivar.llm import LLMConfig, LLMError
from aivar.report import render_text, write_report
from aivar.testfile import load_test, save_test
from aivar.target import Target

logger = logging.getLogger("aivar")


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Aivar: LLM-driven test automation",
        prog="python -m aivar.cli",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # Compile subcommand
    compile_parser = subparsers.add_parser("compile", help="Compile a test from intent")
    compile_parser.add_argument("intent", help="Plain-English intent")
    compile_parser.add_argument("--url", required=True, help="Target URL")
    compile_parser.add_argument("--out", required=True, help="Output file path")
    compile_parser.add_argument("--test-id", default="test_1", help="Test ID")
    compile_parser.add_argument(
        "--headed", action="store_true", help="Run browser in headed mode"
    )

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run a compiled test")
    run_parser.add_argument("path", help="Path to compiled test file")
    run_parser.add_argument(
        "--headed", action="store_true", help="Run browser in headed mode"
    )
    run_parser.add_argument(
        "--report-dir", default="artifacts", help="Directory to write reports (default: artifacts)"
    )
    run_parser.add_argument(
        "--no-report", action="store_true", help="Skip writing report file"
    )
    run_parser.add_argument(
        "--heal", action="store_true", help="Enable self-healing for failed steps"
    )
    run_parser.add_argument(
        "--quarantine-dir", default="quarantine", help="Directory for heal proposals (default: quarantine)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.command == "compile":
        return handle_compile(args)
    elif args.command == "run":
        return handle_run(args)
    else:
        parser.print_help()
        return 1


def handle_compile(args) -> int:
    """Handle the compile subcommand."""
    try:
        config = LLMConfig.from_env()
    except LLMError as e:
        logger.error(f"Failed to load LLM config: {e}")
        return 1

    try:
        report = compile_test(
            intent=args.intent,
            url=args.url,
            test_id=args.test_id,
            config=config,
            headless=not args.headed,
        )

        # Save the test
        save_test(report.test, args.out)

        # Print summary
        logger.info(f"Model: {report.llm.model}")
        logger.info(f"Latency: {report.llm.latency_ms:.0f}ms")
        logger.info(
            f"Tokens: {report.llm.prompt_tokens}+{report.llm.completion_tokens}="
            f"{report.llm.prompt_tokens + report.llm.completion_tokens}"
        )
        logger.info(f"Cost: ${report.llm.cost_usd:.6f}")
        logger.info(
            f"Steps: {report.resolved}/{report.plan_len} resolved, "
            f"{len(report.unresolved)} unresolved"
        )
        if report.unresolved:
            logger.info(f"Unresolved targets: {', '.join(report.unresolved)}")
        logger.info(f"Written to {args.out}")

        # Exit code 1 if not fully compiled
        if not report.fully_compiled:
            logger.warning("Test is not fully compiled")
            return 1

        return 0

    except Exception as e:
        logger.error(f"Compilation failed: {e}")
        return 1


def handle_run(args) -> int:
    """Handle the run subcommand."""
    try:
        test = load_test(args.path)
    except Exception as e:
        logger.error(f"Failed to load test: {e}")
        return 1

    # If --heal is passed, require LLM config
    llm_config = None
    if args.heal:
        try:
            llm_config = LLMConfig.from_env()
        except LLMError as e:
            logger.error(f"--heal requires a valid API key: {e}")
            return 2

    try:
        target = Target(url=test.url, headless=not args.headed)
        result = run_test(
            test,
            target=target,
            headless=not args.headed,
            llm_config=llm_config,
            heal=args.heal,
            quarantine_dir=args.quarantine_dir,
        )

        # Print text report
        report_text = render_text(test, result)
        logger.info("\n" + report_text)

        # Write JSON report if not --no-report
        if not args.no_report:
            report_path = write_report(test, result, out_dir=args.report_dir)
            logger.info(f"Report written to {report_path}")

        # Exit code
        if result.status == "passed":
            return 0
        else:
            return 1

    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
