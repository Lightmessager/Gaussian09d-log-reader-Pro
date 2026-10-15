"""Vendor offline Plotly JS from the installed Python package; no network access."""
import hashlib
import json
from pathlib import Path

import plotly
from plotly.offline import get_plotlyjs

root = Path(__file__).resolve().parents[1]
vendor = root / "src" / "gaussianreadpro" / "resources" / "plot" / "vendor"
vendor.mkdir(parents=True, exist_ok=True)
target = vendor / "plotly.min.js"
target.write_text(get_plotlyjs(), encoding="utf-8")
manifest = {"source": "plotly.offline.get_plotlyjs()", "python_package_version": plotly.__version__,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size,
            "license": "MIT; embedded copyright/license header retained in plotly.min.js"}
(vendor / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest))
