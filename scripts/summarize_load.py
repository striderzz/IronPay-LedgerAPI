"""Turn the raw k6 summaries in a results folder into summary.json and summary.md.

Max transfers/sec = the highest step rate whose achieved throughput is at least 95% of
the target, with transfer error rate under 1% and p95 under P95_LIMIT_MS.

Usage: python -m scripts.summarize_load docs/results/load-<date>
"""

import json
import sys
from pathlib import Path

P95_LIMIT_MS = 500.0


def _metric(summary: dict, name: str) -> dict:
    return summary["metrics"].get(name, {}).get("values", {})


def transfer_stats(path: Path) -> dict:
    s = json.loads(path.read_text())
    dur = _metric(s, "http_req_duration{name:transfer}")
    failed = _metric(s, "http_req_failed{name:transfer}")
    reqs = _metric(s, "http_reqs{name:transfer}") or {}
    checks = _metric(s, "checks")
    return {
        "p50_ms": round(dur.get("med", 0), 2),
        "p95_ms": round(dur.get("p(95)", 0), 2),
        "p99_ms": round(dur.get("p(99)", 0), 2),
        "error_rate": round(failed.get("rate", 0), 4),
        "achieved_rps": round(reqs.get("rate", 0), 1),
        "requests": int(reqs.get("count", 0)),
        "dropped_iterations": int(_metric(s, "dropped_iterations").get("count", 0)),
        "checks_pass_rate": round(checks.get("rate", 0), 4),
    }


def main(folder: str) -> None:
    root = Path(folder)
    out: dict = {"p95_limit_ms": P95_LIMIT_MS}
    if (root / "k6_constant.json").exists():
        out["constant"] = transfer_stats(root / "k6_constant.json")

    steps = []
    for f in sorted(root.glob("k6_step_*.json"), key=lambda p: int(p.stem.split("_")[-1])):
        target = int(f.stem.split("_")[-1])
        st = transfer_stats(f) | {"target_rps": target}
        st["ok"] = (
            st["achieved_rps"] >= 0.95 * target
            and st["error_rate"] < 0.01
            and st["p95_ms"] < P95_LIMIT_MS
        )
        steps.append(st)
    out["steps"] = steps
    passing = [s for s in steps if s["ok"]]
    out["max_ok_rps"] = max((s["target_rps"] for s in passing), default=None)

    for name in ("storm", "ledger_after_constant", "ledger_final", "machine"):
        f = root / f"{name}.json"
        if f.exists():
            out[name] = json.loads(f.read_text())

    (root / "summary.json").write_text(json.dumps(out, indent=2))

    lines = ["# Load test summary", ""]
    if "machine" in out:
        m = out["machine"]
        lines += [f"Machine: {m.get('runner')}, {m.get('cpus')} vCPU, {m.get('mem')}", ""]
    if "constant" in out:
        c = out["constant"]
        lines += [
            f"Constant rate: p50 {c['p50_ms']} ms, p95 {c['p95_ms']} ms, p99 {c['p99_ms']} ms, "
            f"errors {c['error_rate']:.2%}, {c['achieved_rps']} req/s, {c['requests']} requests",
            "",
        ]
    lines += [
        "| target rps | achieved rps | p50 ms | p95 ms | errors | ok |",
        "|---|---|---|---|---|---|",
    ]
    for s in steps:
        lines.append(
            f"| {s['target_rps']} | {s['achieved_rps']} | {s['p50_ms']} | {s['p95_ms']} | "
            f"{s['error_rate']:.2%} | {'yes' if s['ok'] else 'no'} |"
        )
    lines += ["", f"Max transfers/sec meeting the criteria: {out['max_ok_rps']}"]
    if "storm" in out:
        lines += ["", f"Retry storm: {json.dumps(out['storm'])}"]
    if "ledger_final" in out:
        t = out["ledger_final"]
        lines += ["", f"Ledger check: ok={t['ok']}, drift={t['totals']['drift_minor']}"]
    (root / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
