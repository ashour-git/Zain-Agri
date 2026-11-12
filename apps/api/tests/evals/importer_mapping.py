"""Evaluation of the import column mapping: header rules alone, then rules + a live model.

    GROQ_API_KEY=... uv run python -m tests.evals.importer_mapping [--model MODEL ...]

Each case in importer_cases.json is a sheet layout with the correct field (or
null = leave the column out) written by hand for every column. A column is
right when the proposed field equals the expected one, so proposing a field for
a column that should be ignored counts as wrong. Uses a few requests of the
Groq free tier (one per layout that the rules do not fully cover). Not part of
the default test run, and it prints no sheet data beyond the case headers.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from app.modules.assistant.llm import GroqClient
from app.modules.importer.mapping import Column, propose_mapping, rules_mapping

CASES = Path(__file__).with_name("importer_cases.json")
DEFAULT_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]


def _score(columns: list[dict], mapping: dict[int, str | None]) -> tuple[int, list[str]]:
    right, misses = 0, []
    for index, column in enumerate(columns):
        got = mapping.get(index)
        if got == column["expect"]:
            right += 1
        else:
            misses.append(f"{column['header']!r}: expected {column['expect']}, got {got}")
    return right, misses


async def main(models: list[str]) -> int:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    llm = GroqClient(api_key=key, models=models, timeout=30) if key else None
    if llm is None:
        print("No GROQ_API_KEY: evaluating the header rules only.\n")

    total = rules_right = both_right = asked = 0
    try:
        for case in cases:
            columns = [
                Column(index=i, header=c["header"], samples=c["samples"])
                for i, c in enumerate(case["columns"])
            ]
            total += len(columns)
            by_rules = rules_mapping(columns)
            right_rules, _ = _score(case["columns"], dict(by_rules))
            rules_right += right_rules

            combined, used = await propose_mapping(columns, llm)
            asked += 1 if used else 0
            right_both, misses = _score(case["columns"], {i: f for i, (f, _) in combined.items()})
            both_right += right_both
            flag = "ok " if not misses else "MISS"
            print(
                f"[{flag}] {case['name']}: rules {right_rules}/{len(columns)}, "
                f"with assistant {right_both}/{len(columns)}"
                + ("  (assistant asked)" if used else "")
            )
            for miss in misses:
                print(f"       {miss}")
    finally:
        if llm is not None:
            await llm.aclose()

    print(f"\nColumns: {total} in {len(cases)} layouts; assistant asked for {asked} layouts")
    print(f"Header rules alone: {rules_right}/{total} = {rules_right / total:.0%}")
    print(f"Rules + assistant : {both_right}/{total} = {both_right / total:.0%}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", dest="models")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main(args.models or DEFAULT_MODELS)))
