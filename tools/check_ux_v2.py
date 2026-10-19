#!/usr/bin/env python3
"""Collect read-only UX v2 source/package evidence into artifacts/ux-v2/runs.

This helper deliberately does not launch the application or treat historical
screenshots as current evidence. Runtime observations must be captured by an
interactive Windows session and attached to the generated run directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from types import CodeType
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts" / "ux-v2" / "runs"
EXE_CANDIDATES = (
    Path("dist/GaussianReaderPro/GaussianReaderPro.exe"),
    Path("dist/GaussianReadPro/GaussianReadPro.exe"),
    Path("dist/GaussianReadPro-S0/GaussianReadPro-S0.exe"),
)
SOURCE_CHECKS = {
    "main_window": Path("src/gaussianreadpro/ui/main_window.py"),
    "profile_view": Path("src/gaussianreadpro/ui/profile_view.py"),
    "reaction_builder": Path("src/gaussianreadpro/ui/reaction_builder.py"),
    "reaction_network": Path("src/gaussianreadpro/core/reaction_network.py"),
}
FINDINGS = {
    "F01": "默认能量图布局可能隐藏反应编辑入口",
    "F02": "从能量图的新增路径入口可能只打开节点选择对话框",
    "F03": "项目名与保存状态可能在壳层同步时被隐藏",
    "F04": "最近项目的重命名/删除入口可能受限",
    "F05": "未保存项目重命名可能不生效",
    "F06": "首次保存失败或取消时项目名可能丢失",
    "F07": "原始来源导航可能被紧凑页签遮蔽",
    "F08": "反应搭建器的结构编辑可能依赖列表/对话框",
    "F09": "普通路径可能在搭建器显示为空阶段",
    "F10": "预览、应用与保存操作顺序可能不清楚",
    "F11": "关闭编辑器可能丢弃未应用草稿",
    "F12": "多个入口可能直接打开搭建器，缺少用户引导",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_modules(path: Path) -> dict:
    try:
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(path))
        pyz = archive.open_embedded_archive("PYZ.pyz")
        names = sorted(pyz.toc)
        wanted = (
            "gaussianreadpro.ui.reaction_builder",
            "gaussianreadpro.core.reaction_network",
        )
        def code_names(code: CodeType) -> set[str]:
            found = {code.co_name, *code.co_names}
            for value in code.co_consts:
                if isinstance(value, CodeType):
                    found.update(code_names(value))
            return found

        builder_name = wanted[0]
        builder_names = code_names(pyz.extract(builder_name)) if builder_name in pyz.toc else set()
        return {
            "archive_readable": True,
            "entry_count": len(names),
            "modules": {name: name in pyz.toc for name in wanted},
            "symbols": {"ReactionBuilderDialog": "ReactionBuilderDialog" in builder_names},
            "matching_entries": [name for name in names if "reaction_builder" in name or "reaction_network" in name],
        }
    except Exception as exc:  # Report unavailable tooling without claiming absence.
        return {"archive_readable": False, "error": f"{type(exc).__name__}: {exc}", "modules": {}}


def source_evidence() -> dict:
    main = ROOT / SOURCE_CHECKS["main_window"]
    text = main.read_text(encoding="utf-8")
    lines = text.splitlines()
    needles = {
        "shell_hides_project_controls": "for widget in (self.search, self.new_button, self.save_button, self.more_button, self.project_name, self.saved):",
        "builder_tools_visibility_rule": "self.reaction_edit_tools.setVisible(index == 0)",
        "compact_default_focus": "self._compact_focus_index = 1",
        "plus_routes_to_new_path": 'self.profile.pathCreateRequested.connect(lambda: self.manage_path("new"))',
    }
    evidence = {}
    for key, needle in needles.items():
        found = next((i + 1 for i, line in enumerate(lines) if needle in line), None)
        evidence[key] = {
            "present": found is not None,
            "file": SOURCE_CHECKS["main_window"].as_posix(),
            "line": found,
            "evidence_kind": "source_only; runtime_visibility_unverified",
        }
    files = {}
    for key, rel in SOURCE_CHECKS.items():
        path = ROOT / rel
        files[key] = {"path": rel.as_posix(), "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None}
    return {"checks": evidence, "files": files}


def source_identity() -> dict:
    init_file = ROOT / "src/gaussianreadpro/__init__.py"
    text = init_file.read_text(encoding="utf-8") if init_file.is_file() else ""
    fields = {
        "application": r'^APP_NAME\s*=\s*[\"\']([^\"\']+)[\"\']',
        "version": r'^__version__\s*=\s*[\"\']([^\"\']+)[\"\']',
        "version_label": r'^VERSION_LABEL\s*=\s*[\"\']([^\"\']+)[\"\']',
    }
    return {
        key: (match.group(1) if (match := re.search(pattern, text, re.MULTILINE)) else None)
        for key, pattern in fields.items()
    }


def read_build_manifest(path: Path) -> dict:
    manifest_path = path.parent / "build-manifest.json"
    if not manifest_path.is_file():
        return {"path": manifest_path.relative_to(ROOT).as_posix(), "present": False}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "path": manifest_path.relative_to(ROOT).as_posix(),
            "present": True,
            "readable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "path": manifest_path.relative_to(ROOT).as_posix(),
        "present": True,
        "readable": True,
        "application": manifest.get("application"),
        "version": manifest.get("version"),
        "version_label": manifest.get("version_label"),
        "platform": manifest.get("platform"),
        "manifest_sha256": manifest.get("sha256"),
    }


def main() -> int:
    run_id = uuid.uuid4().hex
    out = RUNS / run_id
    out.mkdir(parents=True, exist_ok=False)
    exes = []
    for rel in EXE_CANDIDATES:
        path = ROOT / rel
        if path.is_file():
            stat = path.stat()
            digest = sha256(path)
            manifest = read_build_manifest(path)
            exes.append({
                "path": rel.as_posix(),
                "bytes": stat.st_size,
                "mtime_local": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                "sha256": digest,
                "build_manifest": manifest,
                "manifest_matches_executable_sha256": (
                    manifest.get("manifest_sha256") == digest
                    if manifest.get("present") and manifest.get("readable")
                    else None
                ),
                "frozen_package": frozen_modules(path),
            })
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(ROOT),
        "source_identity": source_identity(),
        "source_evidence": source_evidence(),
        "executables": exes,
        "runtime": {
            "status": "not_captured",
            "reason": "This script is read-only and does not automate the Windows desktop. Attach current screenshots and observations from the interactive desktop session.",
            "window_size_dip": None,
            "device_pixel_ratio": None,
            "scenarios": ["no_project", "imported_ordinary_path", "recipe_path"],
            "F01-F12": {key: {"status": "not_verified_runtime", "observation": None, "evidence": []} for key in FINDINGS},
            "menu_routes": {"plus": "not_verified_runtime", "settings": "not_verified_runtime", "recent": "not_verified_runtime"},
            "first_save_failure_or_cancel": "not_reproduced",
        },
        "historical_screenshots_used_as_current_evidence": False,
    }
    (out / "baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": run_id, "output": str(out), "executable_count": len(exes), "runtime_status": report["runtime"]["status"], "module_checks": {x["path"]: x["frozen_package"]["modules"] for x in exes}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
