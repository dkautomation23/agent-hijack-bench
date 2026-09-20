# -*- coding: utf-8 -*-
"""The command line: pick models, run the cases, write the numbers.

    py -m agent_hijack.cli list
    py -m agent_hijack.cli run --models qwen3:8b,mistral-small --repeats 3
    py -m agent_hijack.cli run --models qwen3:8b --out results/qwen3.json

One command from a cold machine to a table. No interactive prompts, so it drives
cleanly from a script or from an assistant that is not allowed to touch a live
console.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from . import cases as C
from .runner import generate, installed_models, unload
from .score import judge, rate


def _run(models: list[str], repeats: int, seed: int, host: str, defense: str = "none") -> dict:
    have = set(installed_models(host))
    report: dict = {
        "host": host,
        "repeats": repeats,
        "seed": seed,
        "defense": defense,
        "models": {},
    }

    for model in models:
        if model not in have:
            report["models"][model] = {"error": f"not installed - run: ollama pull {model}"}
            print(f"  {model:<22} not installed, skipping", file=sys.stderr)
            continue

        verdicts = []
        speeds = []
        for repeat in range(repeats):
            # A different seed per repeat, derived from the base, so repeats are
            # varied yet the whole run is reproducible from one number.
            run_seed = seed + repeat
            for case in C.CASES:
                gen = generate(
                    model,
                    C.system_for(defense),
                    C.prompt_for(case, defense),
                    host=host,
                    seed=run_seed,
                )
                verdicts.append(judge(case.id, case.family, model, gen.text, C.CANARY, gen.ok))
                if gen.ok and gen.eval_seconds:
                    speeds.append(gen.eval_count / gen.eval_seconds)
            print(f"  {model:<22} pass {repeat + 1}/{repeats}", file=sys.stderr)

        # Hand the card back before the next model asks for it, so each row's
        # speed is the model alone and nobody else's game stutters.
        unload(model, host)

        summary = rate(verdicts)
        if speeds:
            summary["tokens_per_sec_median"] = round(statistics.median(speeds), 1)
        report["models"][model] = summary
        note = summary.get("control_note", "")
        print(
            f"  {model:<22} hijacked {summary['hijacked']}/{summary['attacks']} "
            f"({summary['hijack_rate']}%)  control: {note}",
            file=sys.stderr,
        )

    return report


def _print_table(report: dict) -> None:
    print()
    print(f"{'model':<24}{'hijack rate':>12}{'control':>10}{'tok/s':>9}")
    print("-" * 55)
    for model, summary in report["models"].items():
        if "error" in summary:
            print(f"{model:<24}{'—':>12}{'—':>10}{'—':>9}   {summary['error']}")
            continue
        control = "clean" if summary["control_false_positives"] == 0 else "SUSPECT"
        print(
            f"{model:<24}"
            f"{str(summary['hijack_rate']) + '%':>12}"
            f"{control:>10}"
            f"{summary.get('tokens_per_sec_median', '—'):>9}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-hijack", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("list", help="show the cases and which models are installed")
    show.add_argument("--host", default="http://127.0.0.1:11434")

    run = sub.add_parser("run", help="run the cases against one or more models")
    run.add_argument("--models", required=True, help="comma-separated Ollama model names")
    run.add_argument("--repeats", type=int, default=3, help="passes per case (default 3)")
    run.add_argument("--seed", type=int, default=7, help="base seed (default 7)")
    run.add_argument("--host", default="http://127.0.0.1:11434")
    run.add_argument(
        "--defense",
        choices=("none", "spotlight"),
        default="none",
        help="run the cases behind a mitigation and measure what it buys (default none)",
    )
    run.add_argument("--out", type=Path, help="write the full report here as JSON")

    args = parser.parse_args(argv)

    if args.command == "list":
        print("cases:")
        for case in C.CASES:
            print(f"  {case.id:<22} [{case.family}] {case.description}")
        have = installed_models(args.host)
        print("\ninstalled models:" if have else "\nno models installed (is the server running?)")
        for model in have:
            print(f"  {model}")
        return 0

    if args.command == "run":
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        report = _run(models, args.repeats, args.seed, args.host, args.defense)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nreport written: {args.out}", file=sys.stderr)
        _print_table(report)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
