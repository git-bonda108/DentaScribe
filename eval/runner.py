"""Eval runner — runs every annotated fixture through the orchestrator,
scores it, and writes a report.

CLI: `python -m eval`         → full run, prints summary, writes JSON + MD
     `python -m eval --quiet` → exit code 0 on pass / 1 on fail, no report
     `python -m eval --baseline` → overwrite eval/reports/baseline.json
     `python -m eval --fixture demo-001` → run only one fixture
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.config import load_config
from core.state import SwarmState
from agents.orchestrator import Orchestrator
from utils.fixtures import DEMO_TRANSCRIPTS

from eval.schema import FixtureResult, EvalReport, MetricResult
from eval.ground_truth import GROUND_TRUTH
from eval.metrics import run_all, signability_score, DEFAULT_THRESHOLDS


REPORTS_DIR = Path(__file__).resolve().parent / "reports"
BASELINE_PATH = REPORTS_DIR / "baseline.json"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, cwd=Path(__file__).parent.parent,
        ).decode().strip()
    except Exception:
        return "unknown"


def run_one(swarm: Orchestrator, fixture: dict) -> FixtureResult:
    fid = fixture["id"]
    if fid not in GROUND_TRUTH:
        return FixtureResult(
            fixture_id=fid, patient_name=fixture.get("patient_name", ""),
            errors=[f"No ground truth for fixture {fid}"],
        )

    gt = GROUND_TRUTH[fid]
    state = SwarmState(
        patient_name=fixture["patient_name"],
        doctor_name=fixture["doctor_name"],
        visit_type=fixture.get("visit_type", "emergency_limited"),
    )
    state.raw_transcript = fixture["transcript"]

    t0 = time.time()
    try:
        state = swarm.run(state)
    except Exception as e:
        return FixtureResult(
            fixture_id=fid, patient_name=fixture["patient_name"],
            errors=[f"Orchestrator crashed: {e}"],
            duration_ms=int((time.time() - t0) * 1000),
        )
    duration_ms = int((time.time() - t0) * 1000)

    metrics = run_all(state, gt)
    sig = signability_score(metrics, gt)
    sig_threshold = DEFAULT_THRESHOLDS["signability_score"]

    # A fixture passes iff (a) every individual metric passes its threshold
    # AND (b) the composite signability is >= threshold.
    all_passed = all(m.passed for m in metrics if m.passed is not None)
    return FixtureResult(
        fixture_id=fid,
        patient_name=fixture["patient_name"],
        metrics=metrics,
        signability_score=sig,
        passed=bool(all_passed and sig >= sig_threshold),
        duration_ms=duration_ms,
    )


def run(fixture_filter: Optional[str] = None) -> EvalReport:
    # Respect whatever the user has configured (.env / shell env). Both demo
    # mode and LLM mode are valid eval contexts — the report records which.
    swarm = Orchestrator(load_config())

    fixtures = [f for f in DEMO_TRANSCRIPTS
                if fixture_filter is None or f["id"] == fixture_filter]
    if fixture_filter and not fixtures:
        raise SystemExit(f"No fixture with id {fixture_filter!r}")

    results: List[FixtureResult] = [run_one(swarm, f) for f in fixtures]

    # aggregate by metric name
    aggregate = {}
    if results:
        metric_names = [m.name for m in results[0].metrics]
        for name in metric_names:
            vals = [r.metric(name).score for r in results if r.metric(name)]
            if vals:
                aggregate[name] = round(sum(vals) / len(vals), 3)
        aggregate["signability_score"] = round(
            sum(r.signability_score for r in results) / len(results), 3
        )

    report = EvalReport(
        fixtures=results,
        aggregate=aggregate,
        passed=all(r.passed for r in results) if results else False,
        llm_provider=swarm.llm_provider,
        git_sha=_git_sha(),
        timestamp=datetime.utcnow().isoformat() + "Z",
    )
    return report


# ---------------- output formatters ----------------

def _color(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"\033[{code}m{s}\033[0m"


def _fmt_metric(m: MetricResult) -> str:
    val = f"{m.score:.2f}" if m.is_rate else f"{int(m.score)}"
    thr = ""
    if m.threshold is not None:
        thr = f" (≤{int(m.threshold)})" if not m.is_rate else f" (≥{m.threshold:.2f})"
    mark = "✓" if m.passed else "✗"
    color = "32" if m.passed else "31"
    return _color(f"  {mark} {m.name:<24} {val}{thr}", color)


def print_human(report: EvalReport) -> None:
    print(_color(f"\nDentaScribe eval — {report.timestamp}  provider={report.llm_provider}  sha={report.git_sha}", "1"))
    for r in report.fixtures:
        head = f"\n{r.fixture_id}  {r.patient_name}  (sig={r.signability_score:.2f}, {r.duration_ms}ms)"
        print(_color(head, "32" if r.passed else "31"))
        if r.errors:
            for e in r.errors:
                print(_color(f"  ! {e}", "31"))
            continue
        for m in r.metrics:
            print(_fmt_metric(m))
    print(_color("\nAggregate (mean across fixtures):", "1"))
    for k, v in report.aggregate.items():
        print(f"  {k:<24} {v}")
    overall = "PASS" if report.passed else "FAIL"
    color = "32" if report.passed else "31"
    print(_color(f"\nOverall: {overall}\n", "1;" + color))


def write_reports(report: EvalReport, baseline: bool = False) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS_DIR / f"eval-{stamp}.json"
    md_path   = REPORTS_DIR / f"eval-{stamp}.md"

    json_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))

    # markdown summary
    lines = [f"# DentaScribe eval — {report.timestamp}",
             f"- provider: `{report.llm_provider}`",
             f"- git sha: `{report.git_sha}`",
             f"- overall: **{'PASS' if report.passed else 'FAIL'}**", ""]
    lines.append("## Aggregate (mean)")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    for k, v in report.aggregate.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    for r in report.fixtures:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"## {r.fixture_id} — {r.patient_name} — **{status}** (sig={r.signability_score})")
        if r.errors:
            for e in r.errors:
                lines.append(f"- ⚠ {e}")
            continue
        lines.append("| metric | score | threshold | passed |")
        lines.append("|---|---|---|---|")
        for m in r.metrics:
            val = f"{m.score:.2f}" if m.is_rate else f"{int(m.score)}"
            thr = "—" if m.threshold is None else (f"{m.threshold:.2f}" if m.is_rate else f"{int(m.threshold)}")
            ok = "✓" if m.passed else "✗"
            lines.append(f"| {m.name} | {val} | {thr} | {ok} |")
        lines.append("")
    md_path.write_text("\n".join(lines))

    if baseline:
        BASELINE_PATH.write_text(json.dumps(report.to_dict(), indent=2, default=str))

    return md_path


# ---------------- CLI ----------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval",
                                 description="Run the DentaScribe eval harness.")
    ap.add_argument("--quiet", action="store_true",
                    help="No report files; exit code reflects pass/fail.")
    ap.add_argument("--baseline", action="store_true",
                    help="Also write the result to eval/reports/baseline.json.")
    ap.add_argument("--fixture", default=None,
                    help="Run only this fixture id (e.g. demo-001).")
    args = ap.parse_args(argv)

    report = run(fixture_filter=args.fixture)
    if not args.quiet:
        print_human(report)
        md = write_reports(report, baseline=args.baseline)
        print(_color(f"Report → {md.relative_to(Path.cwd()) if md.is_relative_to(Path.cwd()) else md}", "2"))

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
