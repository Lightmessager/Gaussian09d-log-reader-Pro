"""Sequential final RF7 acceptance; no competing native test windows."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"artifacts/rf7"


def run(script, *args, log):
    with (OUT/log).open("w", encoding="utf-8") as stream:
        result=subprocess.run([sys.executable,str(ROOT/"tools"/script),*args],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    print(script, result.returncode, flush=True)
    if result.returncode: raise RuntimeError(script+" failed; inspect "+log)


def main():
    if "--native-only" not in sys.argv:
        run("run_rf7_tests.py",log="pytest-workspace-final.log")
    run("check_windows_bundle.py",log="windows-smoke.log")
    run("check_profile_rf7.py","--runtime","source",log="source-primary-console.log")
    run("check_profile_rf7.py","--runtime","frozen",log="frozen-primary-console.log")
    run("run_rf7_matrix.py",log="matrix-suite.log")
    run("check_rf7_offline.py",log="offline-console.log")
    run("audit_rf7_bundle.py",log="bundle-audit-console.log")
    frozen=json.loads((OUT/"frozen-primary-latest.json").read_text())
    run("compare_profile_rf7.py",str(Path(frozen["run"])/"default-3d.png"),"--out",str(OUT/"visual-comparison"),log="comparison-console.log")


if __name__=="__main__":main()
