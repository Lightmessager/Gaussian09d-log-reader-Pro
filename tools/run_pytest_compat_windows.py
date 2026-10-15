"""Run pytest with the project's documented, process-local Windows compatibility mask."""
import os
import sys

if os.name == "nt":
    from diagnose_static_runtime import windows_affinity

    modes, _, select_affinity = windows_affinity()
    process_mask = modes["default"] & 0xFFFFFF3F
    if not process_mask:
        raise RuntimeError("The compatibility affinity mask has no available CPUs")
    select_affinity(process_mask)
    print(f"process_affinity={process_mask:#x}", flush=True)

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
