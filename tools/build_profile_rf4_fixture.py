"""RF4 synthetic source/job geometry fixture. Never changes RF0's sources."""
from dataclasses import replace
from pathlib import Path
import build_profile_replica_fixture as base
from gaussianreadpro.storage import ProjectRepository

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/rf4/profile-rf4.grproj"


def orientation(kind="Standard", shift=0):
    rows = [(6,0,0,0),(8,1.2,0,0),(1,-.6,.93,0),(1,-.6,-.93,0)]
    return f" {kind} orientation:\n" + " ---------------------------------------------------------------------\n" + \
        " Center     Atomic      Atomic             Coordinates (Angstroms)\n" + \
        " Number     Number       Type             X           Y           Z\n" + \
        " ---------------------------------------------------------------------\n" + \
        "".join(f" {i} {z} 0 {x+shift:.6f} {y:.6f} {v:.6f}\n" for i,(z,x,y,v) in enumerate(rows,1)) + \
        " ---------------------------------------------------------------------\n"


def main():
    if OUTPUT.exists():
        return OUTPUT
    base.FIXTURE = ROOT / "tests/fixtures/profile_rf4"
    base.OUTPUT = OUTPUT
    original = base.write_synthetic_logs
    def write():
        original()
        for path in base.FIXTURE.rglob("*.log"):
            text = path.read_text(encoding="utf-8").replace("SYNTHETIC RF0", "SYNTHETIC RF4")
            text = text.replace(" SCF Done:", orientation("Input",10)+orientation()+" SCF Done:")
            path.write_text(text,encoding="utf-8")
    base.write_synthetic_logs = write
    base.main()
    with ProjectRepository(OUTPUT) as repo:
        project = repo.load()
        pairs = [[[p.id,p.entries[i].id] for p in project.paths] for i in range(4)]
        a = project.paths[0]
        state = {"mode":"3d","compare":True,"step_pairs":pairs,
                 "barrier":{"path_id":a.id,"from_entry":a.entries[0].id,"to_entry":a.entries[1].id}}
        repo.save(replace(project,revision=project.revision+1,plot_state=state,
                          nodes=tuple(replace(n,role="transition_state") if n.label=="TS1" else n for n in project.nodes)))
    return OUTPUT


if __name__ == "__main__":
    print(main())
