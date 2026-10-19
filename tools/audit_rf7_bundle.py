"""Audit the actual 0.2.0 executable, PE identity, resource bytes and ZIP."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]
from diagnose_static_runtime import windows_affinity
m,_,select=windows_affinity();select(m["default"]&0xffffff3f)
from gaussianreadpro import APP_NAME,__version__
import pefile
from PyInstaller.archive.readers import CArchiveReader


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    bundle=ROOT/"dist"/APP_NAME;exe=bundle/(APP_NAME+".exe");source=ROOT/"src/gaussianreadpro/resources"
    internal=bundle/"_internal/gaussianreadpro/resources";manifest=json.loads((bundle/"build-manifest.json").read_text())
    report={"application":APP_NAME,"version":__version__,"exe":str(exe),"exe_sha256":digest(exe),"checks":{}}
    pe=pefile.PE(str(exe));strings={}
    for item in pe.FileInfo:
        for info in item:
            if hasattr(info,"StringTable"):
                for table in info.StringTable:strings.update({k.decode():v.decode() for k,v in table.entries.items()})
    report["pe_strings"]=strings
    report["checks"]["pe_identity"]=strings["ProductName"]==APP_NAME and strings["FileVersion"]==strings["ProductVersion"]==__version__ and strings["OriginalFilename"]==exe.name
    report["checks"]["manifest_identity"]=manifest["application"]==APP_NAME and manifest["version"]==__version__ and manifest["sha256"]==report["exe_sha256"]
    files={p.relative_to(source).as_posix():digest(p) for p in source.rglob("*") if p.is_file()}
    mismatches=[name for name,value in files.items() if not (internal/name).is_file() or digest(internal/name)!=value]
    report["resource_count"]=len(files);report["resource_mismatches"]=mismatches;report["resource_sha256"]=files
    report["checks"]["source_and_bundled_resources_identical"]=not mismatches and manifest["resources"]==files
    archive=CArchiveReader(str(exe));pyz=archive.open_embedded_archive(next(n for n in archive.toc if n.startswith("PYZ")))
    required=("gaussianreadpro.ui.path_editor","gaussianreadpro.ui.expression_editor","gaussianreadpro.ui.profile_view","gaussianreadpro.services.structure_preview","gaussianreadpro.services.static_plot_worker","matplotlib.backends.backend_svg","matplotlib.backends.backend_pdf")
    report["checks"]["current_modules_frozen"]=all(n in pyz.toc for n in required)
    code=pyz.extract("gaussianreadpro")
    report["checks"]["frozen_python_identity"]=APP_NAME in code.co_consts and __version__ in code.co_consts
    zip_path=ROOT/"artifacts/releases"/(APP_NAME+"-"+__version__+"-Windows-x64-portable.zip")
    with zipfile.ZipFile(zip_path) as z:
        report["checks"]["zip_crc"]=z.testzip() is None
        prefix=APP_NAME+"/";names=z.namelist()
        report["checks"]["zip_layout"]=all(n.startswith(prefix) and ".." not in Path(n).parts for n in names)
        report["checks"]["zip_exe_matches"]=hashlib.sha256(z.read(prefix+exe.name)).hexdigest()==report["exe_sha256"]
        report["checks"]["zip_resources_match"]=all(hashlib.sha256(z.read(prefix+"_internal/gaussianreadpro/resources/"+n)).hexdigest()==v for n,v in files.items())
    report["zip"]={"path":str(zip_path),"bytes":zip_path.stat().st_size,"sha256":digest(zip_path)}
    zip_path.with_suffix(".zip.sha256").write_text(report["zip"]["sha256"]+"  "+zip_path.name+"\n",encoding="utf-8")
    report["passed"]=all(report["checks"].values())
    (ROOT/"artifacts/rf7/bundle-audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="resource_sha256"},indent=2));return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
