"""Private renderer entry point; imports no Qt and executes no project code."""
import json
import os
from pathlib import Path
import warnings


def main(arguments):
    if os.name == "nt":
        # This is the disposable renderer, not the desktop app. Keep native
        # failures observable through exit codes/stderr instead of a blocking WER dialog.
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    if len(arguments) != 2:
        raise ValueError("Expected a render request and output path")
    request, destination = (Path(value).resolve() for value in arguments)
    if request.stat().st_size > 64*1024*1024 or destination.suffix not in (".png", ".svg", ".pdf"):
        raise ValueError("Invalid static render request")
    from .plot_export import _draw_2d_in_process
    payload = json.loads(request.read_text(encoding="utf-8"))
    with warnings.catch_warnings(record=True) as captured:
        result = _draw_2d_in_process(payload, destination)
    result["warnings"] = sorted({str(item.message) for item in captured})
    Path(str(request) + ".result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0
