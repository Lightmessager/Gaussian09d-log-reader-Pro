# GaussianReadPro

A desktop workbench for reading Gaussian output files and building auditable reaction energy profiles.

**GaussianReadPro** parses Gaussian `.log` files locally, organizes calculations by source and job, and helps you compare structures with explicit energy expressions and references. The interface supports Chinese and English.

[简体中文](#简体中文) · [English](#english)

## Download

**Windows x64 preview:** [Download GaussianReadPro v0.1.0-beta.1](https://github.com/Lightmessager/Gaussian09d-log-reader-Pro/releases/download/v0.1.0-beta.1/GaussianReadPro-Windows-x64-portable.zip)

Extract the ZIP and run `GaussianReadPro/GaussianReadPro.exe`. Keep the complete folder together; the executable depends on the bundled `_internal` directory. This is a portable folder, not an installer, and this local build is not code-signed.

If the app crashes on this particular host with the default CPU scheduler, try `Launch-GaussianReadPro-compat.cmd` inside the extracted folder. It only sets CPU affinity for the app and its child processes.

## Highlights

- Batch import Gaussian `.log` files and inspect parsed energies, jobs, and source evidence.
- Build per-structure relative-energy expressions and explicit reference systems.
- Explore interactive, smoothed 2D and 3D reaction energy profiles, compare paths, and inspect selected structures.
- Save and restore projects, workspaces, language, theme, and chart view state.
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

The build writes `dist/GaussianReadPro/` and `artifacts/releases/GaussianReadPro-Windows-x64-portable.zip`. Package verification details are in [`docs/windows-package-validation.md`](docs/windows-package-validation.md). Replace the application artwork at `src/gaussianreadpro/resources/icons/app-icon.png` and the multi-size Windows icon at `packaging/GaussianReadPro.ico`, then rebuild to customize the icon.

## Platform status

The current preview package and native GUI verification target Windows 11 x64. The codebase is designed around Qt, but macOS, Linux, and other Windows versions have not yet been packaged and validated. Do not treat the Windows build as a cross-platform release.

## 简体中文

GaussianReadPro 是用于读取 Gaussian 输出文件并构建可追溯反应能量剖面的桌面工作台。程序在本机解析 `.log` 文件，按来源文件和计算作业整理数据，并使用明确的能量表达式与参考体系比较结构。界面支持中英文切换。

### Windows 预览版

下载 [GaussianReadPro v0.1.0-beta.1](https://github.com/Lightmessager/Gaussian09d-log-reader-Pro/releases/download/v0.1.0-beta.1/GaussianReadPro-Windows-x64-portable.zip)，解压后运行 `GaussianReadPro/GaussianReadPro.exe`。请保留完整文件夹及 `_internal` 目录。本版本是免安装便携包，不是安装程序；当前本机构建未进行数字签名。

若此电脑使用默认 CPU 调度时出现闪退，可尝试运行解压目录中的 `Launch-GaussianReadPro-compat.cmd`。该脚本只为程序及子进程设置 CPU 亲和性。

### 主要功能

- 批量导入 Gaussian `.log` 文件，查看解析出的能量、作业和来源证据。
- 为各结构构建相对能量表达式和显式参考体系。
- 交互查看平滑 2D/3D 反应能量剖面、对比反应路径并检查选中结构。
- 保存和恢复项目、工作区、语言、主题及图表视图。
- 导出图像、独立 HTML、数据表和来源审计信息。
- 中英文界面；运行时图表资源随程序打包，可离线使用。

当前预览版和原生界面验证面向 Windows 11 x64。macOS、Linux 和其他 Windows 版本尚未完成独立打包与验收。
