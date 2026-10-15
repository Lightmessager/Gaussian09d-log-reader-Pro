# Windows 便携包构建与验收

日期：2026-10-15。目标：本机 Windows 11 x64，Python 3.12.14。

## 发布文件

- `artifacts/releases/GaussianReadPro-Windows-x64-portable.zip`：281,935,528 字节，包含 3,402 个文件。
- `dist/GaussianReadPro/GaussianReadPro.exe`：8,088,815 字节。必须保留并一起分发整个 `GaussianReadPro` 目录（或 ZIP 解压后的目录）。
- 格式为 PyInstaller onedir 便携版；不是安装程序，也没有代码签名。
- 本次头像图标版 ZIP SHA-256：`4d516f518773f9e5293e0d9499e1d44552acdc273ba9ef19a706643f306278e3`。
- 本次 `build-manifest.json` 记录 EXE SHA-256：`e74449f67d2cf356df128fb6b8ed8b9c070168aeec612b73e19dc88d38cd9fe5`。

## 构建

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe tools\build_windows.py
```

构建器对自身构建进程使用本机已记录的进程级 CPU 亲和性掩码 `0xFFFFFF3F`，不改系统、BIOS 或其他程序设置。生成完整 onedir 文件夹，并重建 `artifacts/releases/GaussianReadPro-Windows-x64-portable.zip`。

## 验收结果

运行 `.venv\Scripts\python.exe tools\check_windows_bundle.py`，结果通过。自检实际启动冻结版，验证 `profile.html` 加载与 Qt WebChannel 协议 2 握手，报告 Plotly 4.1.1 已载入且无页面错误；并通过冻结版 Matplotlib Agg 子进程输出静态图。渲染报告使用 Matplotlib 3.11.2、Python 3.12.14、Microsoft YaHei，无警告。检查还确认双语资源、WebEngine 子进程、应用入口和运行资源均在 ZIP 中，且不含冲突的外部 ICU DLL。

自检报告为 `artifacts/windows-smoke/webengine-smoke.json`；静态图为 `artifacts/windows-smoke/render-smoke.png`。

在本机默认 CPU 调度下如果遇到此前记录的原生闪退，可尝试包内 `Launch-GaussianReadPro-compat.cmd`。该脚本仅对应用及子进程施加进程亲和性掩码。该兼容入口不构成底层硬件/驱动问题的根因修复。此构建只在当前 Windows 11 x64 主机验收；其他 Windows 版本及 macOS/Linux 仍需单独构建和验证。


## 头像应用图标更新（2026-10-15）

采用用户确认的浅紫发、红瞳、微笑动漫头像。源图为 `src/gaussianreadpro/resources/icons/app-icon.png`，多尺寸 Windows 图标为 `packaging/GaussianReadPro.ico`；PyInstaller EXE 和 Qt 窗口均已使用该头像。头像资源已在冻结包中，`tools/check_windows_bundle.py` 已确认资源存在，冻结版 WebEngine 和 Agg 自检再次通过。新便携 ZIP 为 281,935,528 字节。
