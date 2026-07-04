#!/usr/bin/env python3
"""Run reproducible bench-runner evaluations across models.

This harness creates a clean per-task sandbox using `git worktree add --detach`
at each task's base commit, then executes `bench-runner` against that sandbox.
Optionally it runs each task twice (Context Engine OFF/ON) to validate graph
retrieval localization.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TaskSpec:
    instance_id: str
    base_commit: str
    problem_statement: str
    max_iterations: int
    timeout_secs: int


def run_cmd(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, env=env, text=True, capture_output=True)


def parse_tasks(path: Path) -> list[TaskSpec]:
    raw = path.read_text(encoding="utf-8")
    tasks: list[dict[str, Any]] = []

    stripped = raw.strip()
    if not stripped:
        return []

    if stripped.startswith("["):
        decoded = json.loads(stripped)
        if not isinstance(decoded, list):
            raise ValueError("JSON array expected")
        tasks = decoded
    else:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            tasks.append(json.loads(line))

    out: list[TaskSpec] = []
    for t in tasks:
        out.append(
            TaskSpec(
                instance_id=str(t["instance_id"]),
                base_commit=str(t["base_commit"]),
                problem_statement=str(t["problem_statement"]),
                max_iterations=int(t.get("max_iterations", 40)),
                timeout_secs=int(t.get("timeout_secs", 900)),
            )
        )
    return out


def slug(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        else:
            keep.append("-")
    out = "".join(keep).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "x"


def create_sandbox(repo: Path, sandbox_root: Path, task: TaskSpec, variant: str) -> Path:
    sandbox = sandbox_root / f"{slug(task.instance_id)}-{slug(variant)}"
    if sandbox.exists():
        remove_sandbox(repo, sandbox)
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    cp = run_cmd(["git", "worktree", "add", "--detach", str(sandbox), task.base_commit], cwd=repo)
    if cp.returncode != 0:
        raise RuntimeError(f"git worktree add failed for {task.instance_id}: {cp.stderr.strip()}")
    return sandbox


def remove_sandbox(repo: Path, sandbox: Path) -> None:
    cp = run_cmd(["git", "worktree", "remove", "--force", str(sandbox)], cwd=repo)
    if cp.returncode != 0 and sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)


def run_one(
    bench_runner: Path,
    task: TaskSpec,
    sandbox: Path,
    model: str,
    provider: str,
    base_url: str | None,
    context_engine_url: str | None,
) -> dict[str, Any]:
    spec = {
        "instance_id": task.instance_id,
        "working_dir": str(sandbox),
        "base_commit": task.base_commit,
        "problem_statement": task.problem_statement,
        "max_iterations": task.max_iterations,
        "timeout_secs": task.timeout_secs,
    }
    spec_path = sandbox / ".bench-task-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    cmd = [
        str(bench_runner),
        "--task-file",
        str(spec_path),
        "--model",
        model,
        "--provider",
        provider,
    ]
    if base_url:
        cmd.extend(["--base-url", base_url])
    if context_engine_url:
        cmd.extend([
            "--context-engine-url",
            context_engine_url,
            "--ce-repo-path",
            task.instance_id,
        ])

    cp = run_cmd(cmd)
    if cp.returncode != 0:
        return {
            "instance_id": task.instance_id,
            "status": "error",
            "error": f"bench-runner exit {cp.returncode}",
            "stderr": cp.stderr[-4000:],
            "stdout": cp.stdout[-4000:],
            "patch": "",
            "summary": "",
            "turns": 0,
            "tokens": {"total": 0, "cache_read": 0, "cache_creation": 0},
            "modified_files": [],
            "tool_calls": [],
            "wall_clock_secs": 0.0,
        }

    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as e:
        return {
            "instance_id": task.instance_id,
            "status": "error",
            "error": f"invalid JSON output: {e}",
            "stderr": cp.stderr[-4000:],
            "stdout": cp.stdout[-4000:],
            "patch": "",
            "summary": "",
            "turns": 0,
            "tokens": {"total": 0, "cache_read": 0, "cache_creation": 0},
            "modified_files": [],
            "tool_calls": [],
            "wall_clock_secs": 0.0,
        }


def count_graph_calls(run: dict[str, Any]) -> int:
    calls = run.get("tool_calls") or []
    count = 0
    for c in calls:
        name = str(c.get("name", ""))
        if name in ("codebase_search", "codebase_graph"):
            count += 1
    return count


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(runs)
    done = sum(1 for r in runs if r.get("status") == "done")
    patch_non_empty = sum(1 for r in runs if bool((r.get("patch") or "").strip()))
    graph_calls = sum(count_graph_calls(r) for r in runs)
    avg_tokens = (sum(int((r.get("tokens") or {}).get("total", 0)) for r in runs) / total) if total else 0.0
    avg_turns = (sum(int(r.get("turns") or 0) for r in runs) / total) if total else 0.0
    return {
        "total_runs": total,
        "done_runs": done,
        "patch_non_empty_runs": patch_non_empty,
        "graph_tool_calls": graph_calls,
        "avg_total_tokens": round(avg_tokens, 2),
        "avg_turns": round(avg_turns, 2),
    }


def graph_localization_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for r in runs:
        scenario = r.get("scenario")
        if scenario not in ("graph_off", "graph_on"):
            continue
        key = (str(r.get("instance_id", "")), str(r.get("model", "")))
        pairs.setdefault(key, {})[scenario] = r

    comparable = 0
    on_with_graph_calls = 0
    on_patch_when_off_empty = 0
    for pair in pairs.values():
        if "graph_off" not in pair or "graph_on" not in pair:
            continue
        comparable += 1
        off = pair["graph_off"]
        on = pair["graph_on"]
        if count_graph_calls(on) > 0:
            on_with_graph_calls += 1
        off_patch = bool((off.get("patch") or "").strip())
        on_patch = bool((on.get("patch") or "").strip())
        if on_patch and not off_patch:
            on_patch_when_off_empty += 1

    return {
        "comparable_pairs": comparable,
        "graph_on_runs_with_graph_calls": on_with_graph_calls,
        "graph_on_patch_when_graph_off_empty": on_patch_when_off_empty,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproducible benchmark harness over bench-runner")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Path to repository root")
    parser.add_argument("--tasks", type=Path, required=True, help="Task file (.jsonl or JSON array)")
    parser.add_argument("--bench-runner", type=Path, default=Path("target/release/bench-runner"))
    parser.add_argument("--models", required=True, help="Comma-separated model ids")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--context-engine-url", default=None)
    parser.add_argument("--validate-graph-localization", action="store_true")
    parser.add_argument("--sandbox-root", type=Path, default=Path(".bench-sandboxes"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--keep-sandboxes", action="store_true")

    args = parser.parse_args()

    repo = args.repo.resolve()
    tasks = parse_tasks(args.tasks)
    if not tasks:
        print("No tasks found.", file=sys.stderr)
        return 2

    bench_runner = (repo / args.bench_runner).resolve() if not args.bench_runner.is_absolute() else args.bench_runner
    if not bench_runner.exists():
        print(f"bench-runner not found: {bench_runner}", file=sys.stderr)
        return 2

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("No models supplied.", file=sys.stderr)
        return 2

    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_dir = args.output_dir or (repo / "benchmark-results" / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    sandbox_root = (repo / args.sandbox_root).resolve() if not args.sandbox_root.is_absolute() else args.sandbox_root
    sandbox_root.mkdir(parents=True, exist_ok=True)

    all_runs: list[dict[str, Any]] = []

    for task in tasks:
        for model in models:
            scenarios = ["single"]
            if args.validate_graph_localization and args.context_engine_url:
                scenarios = ["graph_off", "graph_on"]

            for scenario in scenarios:
                use_graph = scenario == "graph_on"
                variant = f"{model}-{scenario}"
                sandbox = create_sandbox(repo, sandbox_root, task, variant)
                try:
                    run = run_one(
                        bench_runner=bench_runner,
                        task=task,
                        sandbox=sandbox,
                        model=model,
                        provider=args.provider,
                        base_url=args.base_url,
                        context_engine_url=args.context_engine_url if use_graph else None,
                    )
                    run["model"] = model
                    run["scenario"] = scenario
                    run["sandbox"] = str(sandbox)
                    all_runs.append(run)
                finally:
                    if not args.keep_sandboxes:
                        remove_sandbox(repo, sandbox)

    summary = summarize(all_runs)
    if args.validate_graph_localization and args.context_engine_url:
        summary["graph_localization"] = graph_localization_summary(all_runs)

    runs_jsonl = out_dir / "runs.jsonl"
    with runs_jsonl.open("w", encoding="utf-8") as f:
        for r in all_runs:
            f.write(json.dumps(r, ensure_ascii=True) + "\n")

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md = [
        "# Benchmark Harness Summary",
        "",
        f"- Total runs: {summary['total_runs']}",
        f"- Done runs: {summary['done_runs']}",
        f"- Runs with non-empty patch: {summary['patch_non_empty_runs']}",
        f"- Total graph tool calls: {summary['graph_tool_calls']}",
        f"- Avg total tokens: {summary['avg_total_tokens']}",
        f"- Avg turns: {summary['avg_turns']}",
        "",
        f"- Output: {runs_jsonl}",
    ]
    if "graph_localization" in summary:
        gl = summary["graph_localization"]
        md.extend(
            [
                "",
                "## Graph Localization Validation",
                "",
                f"- Comparable (off/on) pairs: {gl['comparable_pairs']}",
                f"- Graph-on runs with codebase_search/codebase_graph calls: {gl['graph_on_runs_with_graph_calls']}",
                f"- Graph-on runs producing a patch when graph-off did not: {gl['graph_on_patch_when_graph_off_empty']}",
            ]
        )

    (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(out_dir), "summary": summary}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
