"""Run the local onedir smoke with a startup timeout and captured bootloader output."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "s0"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    executable = ROOT / "dist" / "GaussianReadPro-S0" / "GaussianReadPro-S0.exe"
    if not executable.is_file():
        raise SystemExit("Build the Windows S0 package first")
    startup = None
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    command = [str(executable), "--self-test", "--report", str(OUT / "frozen-smoke.json"),
               "--screenshot", str(OUT / "frozen-preview.png")]
    try:
        with (OUT / "frozen-console.log").open("w", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                    startupinfo=startup, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        raise SystemExit("Frozen process did not complete within 60s; inspect frozen-console.log")
    print(f"Frozen exit code: {result.returncode}; console: {OUT / 'frozen-console.log'}")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
