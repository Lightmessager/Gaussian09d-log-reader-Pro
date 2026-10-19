# GaussianReaderPro v.1.0 Windows package

Date: 2026-10-17. Refreshed from the current workspace after the S8 in-progress fixes. This is a package build, not an S8 completion claim.

## Version identity

- User-facing version label: `v.1.0` in the app, CLI, PE version strings and archive name.
- Python distribution version: `1.0` in `pyproject.toml` and `build-manifest.json`.
- Product name: `GaussianReaderPro`; internal Python package and existing preference/recovery namespace remain compatible.

## Artifacts

- [Portable ZIP](../artifacts/releases/GaussianReaderPro-v.1.0-Windows-x64-portable.zip) — 284,184,622 bytes.
- [ZIP SHA256 file](../artifacts/releases/GaussianReaderPro-v.1.0-Windows-x64-portable.zip.sha256) — `531fcb50d1ad781c8ea28c5263a579f79acc8d9e0381cb1a08c3114b3431b979`.
- EXE: `dist/GaussianReaderPro/GaussianReaderPro.exe`; SHA256 `d6b3b95b6f80c6ef104d747632eb7a5e0d3ad1b7bc1e101a70575fe86c134d49`.
- [Build manifest](../dist/GaussianReaderPro/build-manifest.json), [refreshed package audit](../artifacts/v1/bundle-audit.json), and [current frozen smoke output](../artifacts/v1/windows-smoke-current.json).

## Checks

- Build: `.venv\Scripts\python.exe tools\build_windows.py` completed on Windows 11 x64 with Python 3.12.14 and PyInstaller 6.22.3. It used the repository's process-only affinity mask `0xffffff3f`.
- Version CLI: the packaged EXE printed `GaussianReaderPro v.1.0`.
- Package audit: **9/9 checks passed**: PE identity, manifest identity, all 38 source/package resource hashes, required frozen modules, frozen Python identity, ZIP CRC/layout, EXE hash and bundled resource hashes.
- Refreshed frozen smoke: WebEngine loaded, protocol 2 bridge handshake succeeded, bundled Plotly.js 4.1.1 loaded with no page errors; frozen `--help` and Matplotlib Agg PNG/SVG/PDF also passed with no warnings. The older first-build failure entries below are historical diagnostics; this refreshed build has a passing browser smoke.
- RF8 focused checks passed (11 with the real IRC fixture; 12 after the final UI cleanup and locale check). The complete source suite passed **317/317** before the version-label change; after changing version metadata, the targeted identity/analysis checks passed **11** with one optional local-fixture test skipped. The real-oracle result remains recorded in [RF8 validation](rf8-validation.md).

Rebuild and audit with:

```powershell
.venv\Scripts\python.exe tools\build_windows.py
.venv\Scripts\python.exe tools\audit_v1_bundle.py
```

The ZIP is a portable onedir bundle. Extract the full folder together; do not move the EXE by itself. The archive is local and unsigned; no remote release was published.

This refresh uses the existing `v.1.0` version label. It does not certify S8 completion or add a new release version; current S8 limitations remain in [S8 validation](s8-validation.md).
