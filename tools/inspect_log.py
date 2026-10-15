"""Inspect S1 source/job/line snapshots as JSON, without any GUI dependency."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gaussianreadpro.core.models import EnergyKind, snapshot_to_dict
from gaussianreadpro.core.parser import parse_log, select_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--kind", choices=[kind.value for kind in EnergyKind], default="gibbs_total")
    parser.add_argument("--job-id")
    parser.add_argument("--source-id", help="Use the persisted file UUID to resolve an existing job ID")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.job_id and not args.source_id:
        parser.error("--job-id requires --source-id from the same saved snapshot")
    result = parse_log(args.path, source_file_id=args.source_id)
    selected = select_job(result.source, args.kind, job_id=args.job_id)
    text = json.dumps({"parse": snapshot_to_dict(result), "selection": snapshot_to_dict(selected),
                       "available": selected.available}, ensure_ascii=False, allow_nan=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote snapshot: {args.output}")
    else:
        print(text)
    return 0 if selected.available else 1


if __name__ == "__main__":
    raise SystemExit(main())
