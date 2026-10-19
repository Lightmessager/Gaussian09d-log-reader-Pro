"""Derived RF7 overlays/heatmaps; never used as application screenshots."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("actual",type=Path);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    target=Image.open(ROOT/"docs/design/energy-profile-replica-target.png").convert("RGB")
    actual=Image.open(args.actual).convert("RGB")
    if target.size!=actual.size:raise ValueError("Compare the 1672x941 DPR=1 original captures without scaling")
    Image.blend(target,actual,.5).save(args.out/"derived-overlay-50pct.png")
    a,b=np.array(target,dtype=float),np.array(actual,dtype=float);difference=np.abs(a-b)
    magnitude=difference.max(axis=2)/255
    heat=np.zeros_like(a);heat[:,:,0]=np.minimum(255,magnitude*510);heat[:,:,1]=np.maximum(0,255-np.abs(magnitude-.5)*510)
    Image.fromarray(heat.astype("uint8")).save(args.out/"derived-difference-heatmap.png")
    regions={"topbar":[0,0,1672,50],"navigation":[0,50,196,941],"main_plot":[208,128,1264,930],"inspector":[1272,59,1659,913],"bottom_controls":[477,854,918,910]}
    quiet={"topbar":[430,2,850,16],"navigation":[4,750,187,900],"canvas":[1020,132,1240,170],"panel_edge":[1646,115,1654,890]}
    def samples(rect):
        x0,y0,x1,y1=rect;return a[y0:y1,x0:x1],b[y0:y1,x0:x1]
    report={"target":str(ROOT/"docs/design/energy-profile-replica-target.png"),"actual":str(args.actual.resolve()),"regions":{},"quiet_color_patches":{},
        "interpretation":"Derived diagnostics only. Full-region differences include corrected scientific coordinates, real source structures, the requested product rename and the new path controls. No masks applied."}
    for name,rect in regions.items():
        x,y=samples(rect);diff=np.abs(x-y)
        report["regions"][name]={"rect":rect,"mean_absolute_channel_difference":float(diff.mean()),"median_max_channel_difference":float(np.median(diff.max(axis=2)))}
    for name,rect in quiet.items():
        x,y=samples(rect);source=np.median(x,axis=(0,1));current=np.median(y,axis=(0,1));d=np.abs(source-current)
        report["quiet_color_patches"][name]={"rect":rect,"target_rgb_median":source.tolist(),"actual_rgb_median":current.tolist(),"max_channel_error":float(d.max())}
    report["quiet_color_goal_passed"]=all(v["max_channel_error"]<=8 for v in report["quiet_color_patches"].values())
    (args.out/"comparison.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
