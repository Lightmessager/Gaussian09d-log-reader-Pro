"""Run RF7 against the production source entry or the new Windows executable."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--runtime",choices=("source","frozen"),default="source")
    parser.add_argument("--phase",choices=("primary","restore","matrix"),default="primary")
    parser.add_argument("--case",default="default");parser.add_argument("--project",type=Path);parser.add_argument("--expected",type=Path)
    parser.add_argument("--scale",default="0.8");parser.add_argument("--dpr",type=float,default=1)
    parser.add_argument("--size",default="1672x941");parser.add_argument("--language",default="en");parser.add_argument("--theme",default="dark")
    args=parser.parse_args()
    from diagnose_static_runtime import windows_affinity
    modes,_,select=windows_affinity();select(modes["default"]&0xFFFFFF3F)
    from gaussianreadpro.storage import ProjectRepository
    out=ROOT/"artifacts/rf7"/(args.runtime+"-"+args.phase+"-"+args.case+"-"+uuid4().hex[:8]);out.mkdir(parents=True)
    if args.project is None:
        from build_profile_rf4_fixture import main as fixture
        with ProjectRepository(fixture(),read_only=True) as repo:project=repo.load()
        project=replace(project,plot_state={**project.plot_state,"mode":"3d","compare":True,"viewports":{},"hidden_paths":[],"details_visible":True,"details_drawer_open":False})
        project_file=out/"rf7.grproj"
        with ProjectRepository(project_file,create=True) as repo:repo.save(project)
    else:project_file=args.project.resolve()
    config={"project":str(project_file),"out":str(out),"phase":args.phase,"scale_factor":args.scale,"dpr":args.dpr,
        "size":[int(x) for x in args.size.split("x")],"language":args.language,"theme":args.theme,"frozen":args.runtime=="frozen"}
    if args.expected:config["expected"]=str(args.expected.resolve())
    config_file=out/"config.json";config_file.write_text(json.dumps(config,indent=2),encoding="utf-8")
    command=([str(ROOT/"dist/GaussianReaderPro/GaussianReaderPro.exe")] if args.runtime=="frozen" else [sys.executable,str(ROOT/"tools/run_app.py")])
    with (out/"console.log").open("w",encoding="utf-8") as stream:
        result=subprocess.run([*command,"--validate-rf7",str(config_file)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=900)
    report_file=out/"validation.json"
    report=json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
    summary={"runtime":args.runtime,"phase":args.phase,"exit_code":result.returncode,"passed":report.get("passed",False),"run":str(out),
        "project":str(project_file),"checks":len(report.get("checks",{})),"failures":[k for k,v in report.get("checks",{}).items() if not v],"error":report.get("error"),"performance":report.get("performance")}
    (ROOT/"artifacts/rf7"/(args.runtime+"-"+args.phase+"-latest.json")).write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2));return result.returncode


if __name__=="__main__":raise SystemExit(main())
