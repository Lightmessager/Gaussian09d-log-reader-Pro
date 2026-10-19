"""Audit the current Windows executable, UX v2 modules, resources and ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]
from diagnose_static_runtime import windows_affinity
m,_,select=windows_affinity();select(m["default"]&0xffffff3f)
from gaussianreadpro import APP_NAME,VERSION_LABEL,__version__
import pefile
from PyInstaller.archive.readers import CArchiveReader


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=ROOT/"artifacts/v1/bundle-audit.json")
    args=parser.parse_args()
    bundle=ROOT/"dist"/APP_NAME;exe=bundle/(APP_NAME+".exe");source=ROOT/"src/gaussianreadpro/resources"
    internal=bundle/"_internal/gaussianreadpro/resources";manifest=json.loads((bundle/"build-manifest.json").read_text())
    report={"application":APP_NAME,"version_label":VERSION_LABEL,"python_package_version":__version__,"exe":str(exe),"exe_sha256":digest(exe),"checks":{}}
    pe=pefile.PE(str(exe));strings={}
    for item in pe.FileInfo:
        for info in item:
            if hasattr(info,"StringTable"):
                for table in info.StringTable:strings.update({k.decode():v.decode() for k,v in table.entries.items()})
    report["pe_strings"]=strings
    report["checks"]["pe_identity"]=strings["ProductName"]==APP_NAME and strings["FileVersion"]==strings["ProductVersion"]==VERSION_LABEL and strings["OriginalFilename"]==exe.name
    file_version=tuple(int(value) for value in __version__.split("."))+(0,)
    fixed=pe.VS_FIXEDFILEINFO[0]
    actual_file_version=(fixed.FileVersionMS>>16,fixed.FileVersionMS&0xffff,
                         fixed.FileVersionLS>>16,fixed.FileVersionLS&0xffff)
    report["pe_file_version"]={"actual":actual_file_version,"expected":file_version}
    report["checks"]["pe_numeric_version"]=actual_file_version==file_version
    report["checks"]["manifest_identity"]=manifest["application"]==APP_NAME and manifest["version"]==__version__ and manifest["version_label"]==VERSION_LABEL and manifest["sha256"]==report["exe_sha256"]
    files={p.relative_to(source).as_posix():digest(p) for p in source.rglob("*") if p.is_file()}
    mismatches=[name for name,value in files.items() if not (internal/name).is_file() or digest(internal/name)!=value]
    report["resource_count"]=len(files);report["resource_mismatches"]=mismatches;report["resource_sha256"]=files
    report["checks"]["source_and_bundled_resources_identical"]=not mismatches and manifest["resources"]==files
    archive=CArchiveReader(str(exe));pyz=archive.open_embedded_archive(next(n for n in archive.toc if n.startswith("PYZ")))
    required=("gaussianreadpro.ui.path_editor","gaussianreadpro.ui.expression_editor","gaussianreadpro.ui.profile_view","gaussianreadpro.ui.analysis_pages","gaussianreadpro.services.gaussian_analyses","gaussianreadpro.services.structure_preview","gaussianreadpro.services.static_plot_worker","gaussianreadpro.ui.reaction_builder","gaussianreadpro.ui.reaction_builder_state","gaussianreadpro.ui.reaction_canvas","gaussianreadpro.ui.reaction_stage_inspector","gaussianreadpro.ui.workflow_state","gaussianreadpro.ui.project_actions","gaussianreadpro.services.builder_drafts","gaussianreadpro.validation_ux_v2_u8","matplotlib.backends.backend_svg","matplotlib.backends.backend_pdf")
    report["checks"]["current_modules_frozen"]=all(n in pyz.toc for n in required)
    code=pyz.extract("gaussianreadpro")
    report["checks"]["frozen_python_identity"]=APP_NAME in code.co_consts and __version__ in code.co_consts
    zip_path=ROOT/"artifacts/releases"/(APP_NAME+"-"+VERSION_LABEL+"-Windows-x64-portable.zip")
    with zipfile.ZipFile(zip_path) as z:
        report["checks"]["zip_crc"]=z.testzip() is None
        prefix=APP_NAME+"/";names=z.namelist()
        report["checks"]["zip_layout"]=all(n.startswith(prefix) and ".." not in Path(n).parts for n in names)
        report["checks"]["zip_exe_matches"]=hashlib.sha256(z.read(prefix+exe.name)).hexdigest()==report["exe_sha256"]
        report["checks"]["zip_resources_match"]=all(hashlib.sha256(z.read(prefix+"_internal/gaussianreadpro/resources/"+n)).hexdigest()==v for n,v in files.items())
    report["zip"]={"path":str(zip_path),"bytes":zip_path.stat().st_size,"sha256":digest(zip_path)}
    zip_path.with_suffix(".zip.sha256").write_text(report["zip"]["sha256"]+"  "+zip_path.name+"\n",encoding="utf-8")
    report["passed"]=all(report["checks"].values())
    audit_path=args.out.resolve();audit_path.parent.mkdir(parents=True,exist_ok=True)
    audit_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="resource_sha256"},indent=2));return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
