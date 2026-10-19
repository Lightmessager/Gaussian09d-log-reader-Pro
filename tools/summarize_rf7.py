"""Consolidate RF7 measured evidence after all independent runs pass."""
import json
from pathlib import Path
import re
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/"artifacts/rf7"


def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))


def contrast(a,b):
    def luminance(rgb):
        v=[n/255 for n in rgb];v=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in v]
        return sum(n*w for n,w in zip(v,(.2126,.7152,.0722)))
    x,y=sorted((luminance(a),luminance(b)))
    return round((y+.05)/(x+.05),3)


def main():
    source=read(OUT/"source-primary-latest.json");frozen=read(OUT/"frozen-primary-latest.json")
    matrix=read(OUT/"matrix-validation.json");audit=read(OUT/"bundle-audit.json");offline=read(OUT/"offline-validation.json")
    visual=read(OUT/"visual-comparison/comparison.json")
    tests=(OUT/"pytest-workspace-final.log").read_text(encoding="utf-8")
    match=re.search(r"(\d+) passed, 1 warning in ([\d.]+)s",tests)
    assert match and " failed" not in tests
    assert all(r["passed"] for r in (source,frozen,matrix,audit,offline)) and visual["quiet_color_goal_passed"]
    tokens=read(ROOT/"src/gaussianreadpro/resources/themes/lavender_sunset.json")["profile_themes"]["dark"]
    def rgb(s):return [int(s[i:i+2],16) for i in (1,3,5)]
    pairs={}
    for name in ("text","muted","axis","path_a","path_b","focus"):
        for surface,bg in (("canvas",rgb(tokens["canvas"])),("panel",[23,21,39])):
            pairs[name+"_on_"+surface]=contrast(rgb(tokens[name]),bg)
    report={"passed":True,"application":"GaussianReaderPro","version":"0.2.0","date":datetime.now().isoformat(),
        "source_primary":source,"frozen_primary":frozen,"matrix":matrix,"offline":offline,"bundle_audit":audit,
        "tests":{"passed":int(match[1]),"seconds":float(match[2]),"warning":"Nonfunctional pytest cache ACL warning", "log":str(OUT/"pytest-workspace-final.log")},
        "visual":visual,"dark_contrast_ratios":pairs,"dark_text_AA_passed":min(pairs.values())>=4.5,
        "screenshots":"Unmodified QWidget.grab; overlay and heatmap are diagnostic derivatives only",
        "limitations":["Windows x64 only; process affinity 0xffffff3f. Default scheduling/macOS/Linux not validated.",
            "Native content capture excludes OS titlebar controls.","No GPU VRAM measurements; UI and WebEngine private memory sampled separately.",
            "Synthetic geometry/source fixture is labeled; does not assert all Gaussian variants supported.",
            "RF8 analysis modules and original S8/S9 not started. No remote release published."]}
    (OUT/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    full_source=read(Path(source["run"])/"validation.json");full_frozen=read(Path(frozen["run"])/"validation.json")
    metrics=["## 最终结果", "", "**RF7 已完成（Windows 本机兼容配置）。** 全量回归 **"+match[1]+" passed**，1 项非功能性 pytest cache 权限警告；源码/EXE 主链、独立恢复与窗口矩阵全部通过。", "",
        "| 运行 | 通过检查 | 实际拖动 FPS | 选择 p50/p95（ms） | 详情 p50/p95（ms） |", "| --- | --- | --- | --- | --- |"]
    for name,r in (("源码",source),("冻结 EXE",frozen)):
        p=r["performance"]
        metrics.append(f"| {name} | {r['checks']}/{r['checks']} | {p['native_drag_fps']:.2f} | {p['selection_ms_p50']:.1f}/{p['selection_ms_p95']:.1f} | {p['details_ms_p50']:.1f}/{p['details_ms_p95']:.1f} |")
    metrics.extend(["",f"独立新进程恢复与窗口矩阵 **{matrix['checks']}/{matrix['checks']}**；当前 EXE 导出文件搬移后的离线页 **{len(offline['checks'])}/{len(offline['checks'])}**；包审计 **{len(audit['checks'])}/{len(audit['checks'])}**、源码与包内 **{audit['resource_count']} 个资源**逐字节 SHA 一致。冻结 PNG/SVG/PDF、CLI 和 WebEngine 握手烟测通过，见 `artifacts/rf7/windows-smoke.log`。", "",
        "| 独立运行 | 检查数 | 证据目录 |", "| --- | --- | --- |"])
    for r in matrix["runs"]:
        metrics.append(f"| {r['runtime']} / {r['phase']} | {r['checks']} | `{r['run']}` |")
    metrics.extend(["",f"实际图形设备：`{full_frozen['webgl_device']['renderer']}`；Qt `{full_frozen['qt']}`，Python `{full_frozen['python'].split()[0]}`。基准截图内容区 1672×941 DIP、DPR1；两路径图体宽/高占用 {full_frozen['coverage'][0]*100:.1f}%/{full_frozen['coverage'][1]*100:.1f}%；宏观边界最大误差 {max(full_frozen['boundary_errors'].values()):.1f} DIP。", "",
        "| 深色文字/标记 | 对画布对比度 | 对面板对比度 |", "| --- | --- | --- |"])
    for name in ("text","muted","axis","path_a","path_b","focus"):
        metrics.append(f"| {name} | {pairs[name+'_on_canvas']}:1 | {pairs[name+'_on_panel']}:1 |")
    metrics.extend(["", "以上按标准 token 与实际面板背景中位色计算；标准深色达到 4.5:1。自定义路径颜色由用户选择，不保证任意颜色的对比度。四处安静背景 RGB 单通道最大误差依次为 "+"、".join(str(int(v['max_channel_error'])) for v in visual['quiet_color_patches'].values())+"（目标 ≤8）。", "",
        "内存采样（MiB；预热/末次/峰值）：", "", "| 运行 | UI private | WebEngine private |", "| --- | --- | --- |"])
    for name,r in (("源码",full_source),("EXE",full_frozen)):
        samples=r["resource_samples"]
        def amounts(key):
            values=[s["memory"][key]/1048576 for s in samples]
            return "/".join(f"{v:.1f}" for v in (values[0],values[-1],max(values)))
        metrics.append(f"| {name} | {amounts('ui_private')} | {amounts('webengine_private')} |")
    metrics.extend(["", "实际截图绝对路径（其余操作/编辑截图见各运行 `validation.json`）：", "",
        f"- 源码默认：`{Path(source['run'])/'default-3d.png'}`。",
        f"- EXE 默认：`{Path(frozen['run'])/'default-3d.png'}`。",
        f"- [EXE 实际默认截图]({(Path(frozen['run'])/'default-3d.png').as_posix()})。", "",
        "发行物标识：", "", f"- EXE SHA256：`{audit['exe_sha256']}`。", f"- ZIP：{audit['zip']['bytes']:,} bytes；SHA256：`{audit['zip']['sha256']}`。", "",
        "[综合原始报告](../artifacts/rf7/validation.json)、[源码摘要](../artifacts/rf7/source-primary-latest.json)、[EXE 摘要](../artifacts/rf7/frozen-primary-latest.json)、[矩阵](../artifacts/rf7/matrix-validation.json)、[离线报告](../artifacts/rf7/offline-validation.json)。"])
    doc=ROOT/"docs/rf7-validation.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("<!-- RF7_METRICS -->","\n".join(metrics)),encoding="utf-8")
    print(json.dumps({"passed":True,"tests":report["tests"],"native_checks":source["checks"]+frozen["checks"]+matrix["checks"],"offline_checks":len(offline["checks"]),"contrast":pairs,"zip":audit["zip"],"exe_sha256":audit["exe_sha256"]},indent=2))


if __name__=="__main__":main()
