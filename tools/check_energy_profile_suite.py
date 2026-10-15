"""Sequential native EP regressions and final DPR matrix; keep exact per-run logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main(only=None):
    run = ROOT / "artifacts/ui-glass/ep6" / ("suite-" + uuid4().hex)
    run.mkdir(parents=True)
    sources = [ROOT / "src/gaussianreadpro/core/plot_spec.py", ROOT / "src/gaussianreadpro/resources/plot/profile.js",
               *[ROOT / "src/gaussianreadpro/ui" / name for name in
                 ("main_window.py", "profile_view.py", "profile_preview.py", "plot_inspector.py", "theme.py", "glass_widgets.py")],
               ROOT / "src/gaussianreadpro/services/plot_export.py"]
    source_hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    cases = [(f"ep{stage}", f"check_energy_profile_ep{stage}.py", []) for stage in (2, 3, 4, 5)]
    cases += [("ep6-dpr1", "check_energy_profile_ep6.py", ["--scale-factor", ".8", "--expected-dpr", "1"]),
              ("ep6-dpr1.5", "check_energy_profile_ep6.py", ["--scale-factor", "1.2", "--expected-dpr", "1.5", "--skip-performance"]),
              ("ep6-dpr2", "check_energy_profile_ep6.py", ["--scale-factor", "1.6", "--expected-dpr", "2", "--skip-performance"])]
    reports = []
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    environment.pop("QT_SCALE_FACTOR", None)
    for name, script, arguments in cases:
        if only and name not in only:
            continue
        try:
            process = subprocess.run([sys.executable, str(ROOT / "tools" / script), *arguments],
                                     cwd=ROOT, env=environment, capture_output=True, timeout=300)
            stdout = process.stdout.decode("utf-8", errors="replace")
            (run / f"{name}.stdout.txt").write_text(stdout, encoding="utf-8")
            (run / f"{name}.stderr.txt").write_text(process.stderr.decode("utf-8", errors="replace"), encoding="utf-8")
            report = json.loads(stdout[stdout.index("{"):])
            entry = {"name": name, "passed": process.returncode == 0 and report.get("passed") is True,
                     "exit_code": process.returncode, "run": report.get("run"), "error": report.get("error")}
        except Exception as error:
            entry = {"name": name, "passed": False, "error": str(error)}
        reports.append(entry)
        print(f"{name}: {'passed' if entry['passed'] else 'FAILED'}", flush=True)
    unchanged = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in source_hashes.items())
    result = {"passed": bool(reports) and all(item["passed"] for item in reports) and unchanged,
              "run": str(run), "reports": reports, "source_unchanged_during_suite": unchanged, "source_sha256": source_hashes}
    (run / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Comma-separated case names; omitted runs the complete suite")
    args = parser.parse_args()
    raise SystemExit(main(set(args.only.split(",")) if args.only else None))
