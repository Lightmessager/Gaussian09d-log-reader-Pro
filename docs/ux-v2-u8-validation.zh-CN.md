# UX v2 U8 验收：Windows 2.0.0 发行包与 EXE

日期：2026-10-18  
范围：全量重建 Windows x64 便携包、审计冻结模块/资源、从 EXE 默认首页实际点击新建/保存/改名/搭建入口，并检查图表渲染。

## 结果

2.0.0 onedir 便携包已构建。PE/ZIP/资源审计 10 项全部通过；EXE 默认首页可见项目名、版本、新建、保存和“编辑反应路径”，实际点击后成功创建并改名项目、打开搭建器。改名前后项目 UUID 保持不变。Agg PNG、SVG、PDF 导出通过。

WebEngine 页面烟测未通过：源码与冻结 EXE 均报告 `profile.html failed to load`，无 Qt WebChannel 协议握手，子进程标准错误为空。这与 U7 已记录的本机本地页面失败一致；当前证据不能将其归因于 2.0.0 冻结包。U7 已验证主应用显示失败提示并切换到可用的原生二维图；U8 的默认首页搭建/改名路线不依赖 WebEngine。WebEngine 页面/3D 运行在本机仍未验收通过。

## 发行产物

- 便携 ZIP：[`GaussianReaderPro-2.0.0-Windows-x64-portable.zip`](../artifacts/releases/GaussianReaderPro-2.0.0-Windows-x64-portable.zip)，284,358,713 bytes
- ZIP SHA256：`d67ee20cdbc66f8e96dce3ebe70a8c9d177400dadef62f4ac90335811c132d00`（同目录 `.zip.sha256`）
- EXE：`dist/GaussianReaderPro/GaussianReaderPro.exe`，9,932,081 bytes
- EXE SHA256：`e9fdc3e652835b92847d756130e7db1cee7f210eb3662ccdfbd9403192faa587`
- 运行环境：Windows 11 22631、Python 3.12.14、PyInstaller 6.22.3、Qt 6.12.0；构建与 Qt 验收进程使用本机既有进程掩码 `0xffffff3f`，未改系统设置。

## 验收证据

| 项目 | 命令/结果 |
|---|---|
| 全量构建 | `.venv\Scripts\python.exe tools\build_windows.py`，退出 0；重新生成 EXE、便携目录和 ZIP |
| 包审计 | `.venv\Scripts\python.exe tools\audit_v1_bundle.py --out artifacts\ux-v2\u8\bundle-audit.json`，10/10 通过 |
| 冻结模块 | U7 的 reaction builder、canvas、inspector、workflow、project actions、builder drafts 等所需模块均在 PYZ 中 |
| 身份与版本 | PE 字符串、数值版本 `2.0.0.0`、清单和 CLI `--version` 一致；`--help` 正常 |
| ZIP 与资源 | CRC、目录结构、ZIP 内 EXE 哈希均通过；38 个资源与源码 SHA 完全一致 |
| 静态图 | 冻结 Agg 输出 PNG 55,343 bytes、SVG 31,585 bytes、PDF 12,931 bytes；渲染结果标记 `python_isolated=true`、无警告 |
| WebEngine | 源码与 EXE 均退出 1，报告 `profile.html failed to load`；协议/Plotly 字段为空。详见 `artifacts/ux-v2/u8/source-webengine-smoke.json`、`artifacts/ux-v2/u8/bundle-smoke/webengine-smoke.json` |
| EXE 用户界面 | `.venv\Scripts\python.exe tools\check_ux_v2_u8_frozen.py`，退出 0，7/7 检查通过；机器报告及截图见下方 |
| 回归用例 | `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_ux_v2_u8_helper.py tests\test_product_identity.py`，6 passed。路径覆盖 helper 曾先以缺失函数导入失败，再实现后通过 |

桌面报告：`artifacts/ux-v2/u8/29199ad342fe413ba0b4e687c48a4be8/frozen-ui-validation.json`。截图：同目录 `default-home.png`（1440×900，DPR 1.0）和 `reaction-builder.png`（1180×760，DPR 1.0）。验证流程创建 `U8 Frozen Project.grproj`，再通过项目名控件改为 `U8 Frozen Renamed.grproj`，确认旧文件消失、新文件存在且 project UUID 不变；随后点击首页可见按钮打开“反应路径搭建 · 物质关系网”。

本次没有运行单进程仓库全量测试。构建日志有一条未安装的可选 QML 插件提示，以及 EXE 资源操作各一次短暂重试；最终构建退出 0，版本/模块/资源审计和 EXE 桌面验收均完成。WebEngine 失败作为明确限制保留，未把它计入通过项。
\n\n说明：本报告记录本机发行包的构建与验收证据。该 EXE、ZIP、截图和运行日志属于本机生成/验收产物，未包含在 GitHub 源码同步中。
