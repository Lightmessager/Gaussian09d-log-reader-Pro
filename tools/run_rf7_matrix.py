"""Sequential RF7 windows: fresh sessions, sizes, languages, themes and DPR."""
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

ROOT=Path(__file__).resolve().parents[1];folder=ROOT/"artifacts/rf7"


def main():
    latest=folder/"frozen-primary-latest.json";deadline=monotonic()+900
    while not latest.exists():
        if monotonic()>deadline:raise TimeoutError("Waiting for frozen primary validation")
        sleep(2)
    frozen=json.loads(latest.read_text());source=json.loads((folder/"source-primary-latest.json").read_text())
    if not frozen["passed"]:raise RuntimeError("Frozen primary failed; resolve before matrix")
    jobs=[]
    for runtime,record in (("source",source),("frozen",frozen)):
        jobs.append(["--runtime",runtime,"--phase","restore","--project",record["project"],"--expected",str(Path(record["run"])/"restart-expected.json")])
    jobs.extend([
        ["--runtime","source","--phase","matrix","--case","cn-light-1440","--size","1440x900","--language","zh_CN","--theme","light"],
        ["--runtime","source","--phase","matrix","--case","en-mid-1100","--size","1100x820"],
        ["--runtime","frozen","--phase","matrix","--case","en-dpr1_5","--scale","1.2","--dpr","1.5"],
        ["--runtime","frozen","--phase","matrix","--case","cn-narrow-dpr2","--scale","1.6","--dpr","2","--size","840x680","--language","zh_CN"],
    ])
    reports=[]
    for index,args in enumerate(jobs):
        result=subprocess.run([sys.executable,str(ROOT/"tools/check_profile_rf7.py"),*args],capture_output=True)
        (folder/("matrix-"+str(index)+"-console.log")).write_bytes(result.stdout+b"\n"+result.stderr)
        record=json.loads(result.stdout) if result.stdout.strip() else {"passed":False,"error":result.stderr.decode(errors="replace")}
        reports.append(record)
        (folder/"matrix-validation.json").write_text(json.dumps({"passed":False,"status":"running","runs":reports},indent=2),encoding="utf-8")
    summary={"passed":all(r["passed"] for r in reports),"status":"complete","runs":reports,"checks":sum(r.get("checks",0) for r in reports)}
    (folder/"matrix-validation.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2));return 0 if summary["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
