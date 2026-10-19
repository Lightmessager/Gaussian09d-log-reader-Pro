# GaussianReaderPro 2.0.0

A desktop workbench for reading Gaussian output files and building auditable reaction energy profiles.

**GaussianReaderPro** parses Gaussian `.log` files locally, organizes calculations by source and job, and helps you compare structures with explicit energy expressions and references. The interface supports Chinese and English. Version 2.0.0 includes the reaction path builder, project naming and save-state controls, guided job selection, editable material and stage cards, branch connections, selectable issue lists, and safer draft/save/undo handling. See [`docs/LUNA_WORKFLOW_UX_V2_PROJECT_BRIEF.zh-CN.md`](docs/LUNA_WORKFLOW_UX_V2_PROJECT_BRIEF.zh-CN.md) and the U8 validation report for scope and status.

[简体中文](#简体中文) · [English](#english)

## Source repository

This repository contains application source, tests, packaging scripts, and project documentation. Windows release executables and portable archives are distributed separately and are not stored in this source repository. The 2.0.0 package and UI verification record is in [`docs/ux-v2-u8-validation.zh-CN.md`](docs/ux-v2-u8-validation.zh-CN.md).

## Highlights

- Batch import Gaussian `.log` files and inspect parsed energies, jobs, and source evidence.
- Build per-structure relative-energy expressions and explicit reference systems.
- Explore interactive 2D and 3D reaction energy profiles, compare paths, and inspect selected structures.
- Create and rename projects, preserve drafts, and manage save state and undo.
- Export chart images, standalone HTML, tables, and source-audit data.
- Use Chinese or English UI; chart resources are bundled for offline operation.

## Screenshots and design

The application icon and visual design source files are in [`src/gaussianreadpro/resources/icons/`](src/gaussianreadpro/resources/icons/) and [`docs/design/`](docs/design/).

## Run from source

The supported development environment currently targets **Python 3.12**. In PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tools\vendor_plotly.py
.\.venv\Scripts\python.exe tools\run_app.py
```

To open an existing project, pass its `.grproj` path to `tools\run_app.py`. See [`docs/handoff.md`](docs/handoff.md) and [`AI_HANDOFF.md`](AI_HANDOFF.md) for implementation details.

## Build the Windows portable package

On Windows with Python 3.12 and the locked dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tools\build_windows.py
.\.venv\Scripts\python.exe tools\check_windows_bundle.py
```

The build writes to `dist/` and `artifacts/releases/`, which are local generated outputs and are excluded from this repository. Packaging and validation notes are in [`docs/`](docs/).

## Platform status

The 2.0.0 preview package and native GUI verification target Windows 11 x64. The codebase is designed around Qt, but macOS, Linux, and other Windows versions have not yet been packaged and validated. WebEngine local page loading remains an open validation issue; the application falls back to its native 2D chart when that page is unavailable.

## 简体中文

GaussianReaderPro 2.0.0 是用于读取 Gaussian 输出文件并构建可追溯反应能量剖面的桌面工作台。程序在本机解析 `.log` 文件，按来源文件和计算作业整理数据，并使用明确的能量表达式与参考体系比较结构。新版包含反应路径搭建器、项目命名与保存状态、导入后的作业选择引导、物质卡/阶段卡/分支连线、可定位的问题清单，以及草稿保护、应用并保存、失败重试和撤销流程。详细范围见[项目书](docs/LUNA_WORKFLOW_UX_V2_PROJECT_BRIEF.zh-CN.md)及 U8 验收报告。

### 源码仓库说明

本仓库保存应用源码、测试、打包脚本和项目文档。Windows EXE 与便携 ZIP 单独分发，不放在源码仓库中。2.0.0 的打包与界面验收记录见 [`docs/ux-v2-u8-validation.zh-CN.md`](docs/ux-v2-u8-validation.zh-CN.md)。

### 从源码运行

当前开发环境面向 **Python 3.12**。在仓库根目录的 PowerShell 中运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tools\vendor_plotly.py
.\.venv\Scripts\python.exe tools\run_app.py
```

打开已有项目时，将 `.grproj` 路径传给 `tools\run_app.py`。开发说明见 [`docs/handoff.md`](docs/handoff.md) 与 [`AI_HANDOFF.md`](AI_HANDOFF.md)。

### Windows 便携包

可以按上方打包命令在 Windows 11 x64 上构建。本地生成的 `dist/` 与 `artifacts/releases/` 不提交到源码仓库。当前预览版尚未在 macOS、Linux 或其他 Windows 版本完成打包验收。WebEngine 本地页面加载仍有已记录的问题；页面不可用时，应用会回退到原生二维图。

