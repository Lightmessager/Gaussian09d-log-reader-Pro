"""Reproduce Matplotlib startup in fresh processes, without importing Qt.

The optional Windows affinity matrix affects only this diagnostic process and
its children. Original affinity is restored, and no system settings are changed.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from time import perf_counter
from uuid import uuid4


def windows_affinity():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    kernel.GetProcessAffinityMask.restype = wintypes.BOOL
    kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = wintypes.BOOL
    kernel.GetSystemCpuSetInformation.argtypes = [ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), wintypes.HANDLE, wintypes.ULONG]
    kernel.GetSystemCpuSetInformation.restype = wintypes.BOOL
    process = kernel.GetCurrentProcess()
    original, system = ctypes.c_size_t(), ctypes.c_size_t()
    if not kernel.GetProcessAffinityMask(process, ctypes.byref(original), ctypes.byref(system)):
        raise ctypes.WinError(ctypes.get_last_error())
    length = wintypes.ULONG()
    kernel.GetSystemCpuSetInformation(None, 0, ctypes.byref(length), process, 0)
    buffer = ctypes.create_string_buffer(length.value)
    if not kernel.GetSystemCpuSetInformation(buffer, length, ctypes.byref(length), process, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    offset, topology = 0, []
    while offset < length.value:
        size, kind = struct.unpack_from("=II", buffer.raw, offset)
        if size < 20 or offset + size > length.value:
            raise ValueError("Unexpected CPU set record")
        if kind == 0:
            group = struct.unpack_from("=H", buffer.raw, offset + 12)[0]
            logical, core, _, _, efficiency = struct.unpack_from("=BBBBB", buffer.raw, offset + 14)
            topology.append(dict(group=group, logical=logical, core=core, efficiency=efficiency))
        offset += size

    def select(mask):
        if not kernel.SetProcessAffinityMask(process, mask):
            raise ctypes.WinError(ctypes.get_last_error())

    modes = {"default": original.value}
    classes = sorted({item["efficiency"] for item in topology if item["group"] == 0})
    if len(classes) > 1:
        for name, efficiency in (("efficient", classes[0]), ("performance", classes[-1])):
            mask = sum(1 << item["logical"] for item in topology if item["group"] == 0 and item["efficiency"] == efficiency)
            if mask & original.value:
                modes[name] = mask & original.value
    return modes, topology, select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--performance-cores", action="store_true", help="Test individual high-performance cores; diagnostic processes only")
    parser.add_argument("--cpus", help="Comma-separated logical CPU indices for a controlled diagnostic comparison")
    parser.add_argument("--package-root", type=Path, help="Isolated dependency candidate for A/B checks")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "artifacts/ui-glass/g4/static-runtime" / uuid4().hex
    output.mkdir(parents=True)
    modes, topology, select = windows_affinity() if os.name == "nt" else ({"default": None}, [], lambda mask: None)
    if args.cpus:
        original_mask = modes["default"]
        modes = {"default": original_mask}
        for value in args.cpus.split(","):
            index = int(value)
            if index < 0 or index >= ctypes.sizeof(ctypes.c_size_t)*8 or not (original_mask & (1 << index)):
                raise ValueError("Logical CPU outside the current process affinity")
            modes["cpu" + str(index)] = 1 << index
    elif args.performance_cores and topology:
        highest = max(item["efficiency"] for item in topology)
        seen = set()
        for item in topology:
            if item["group"] == 0 and item["efficiency"] == highest and item["core"] not in seen:
                seen.add(item["core"])
                mask = (1 << item["logical"]) & modes["default"]
                if mask:
                    modes["cpu" + str(item["logical"])] = mask
        modes.pop("performance", None)
    elif not args.matrix:
        modes = {"default": modes["default"]}
    report = {"executable": sys.executable, "python": sys.version, "topology": topology,
              "package_root": str(args.package_root) if args.package_root else None,
              "masks": {name: hex(mask) if mask is not None else None for name, mask in modes.items()}, "runs": []}
    original = modes["default"]
    try:
        for index in range(args.rounds):
            for name, mask in modes.items():
                select(mask)
                started = perf_counter()
                code = ("import sys\n"
                        "if sys.platform == 'win32':\n import ctypes\n ctypes.windll.kernel32.SetErrorMode(3)\n"
                        "if len(sys.argv)>1: sys.path.insert(0,sys.argv[1])\n"
                        "import matplotlib.figure; import matplotlib; print(matplotlib.__version__)\n")
                command = [sys.executable, "-I", "-X", "faulthandler", "-c", code]
                if args.package_root:
                    command.append(str(args.package_root.resolve()))
                result = subprocess.run(command, capture_output=True, timeout=40)
                record = {"round": index, "mode": name, "returncode": result.returncode,
                          "seconds": perf_counter()-started, "stdout": result.stdout.decode("utf-8", "replace"),
                          "stderr": result.stderr.decode("utf-8", "replace")}
                report["runs"].append(record)
                (output / "diagnostic.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps({key:record[key] for key in ("round", "mode", "returncode", "seconds")}), flush=True)
    finally:
        select(original)
    print(json.dumps({"report": str(output / "diagnostic.json"), "masks": report["masks"]}), flush=True)


if __name__ == "__main__":
    main()
