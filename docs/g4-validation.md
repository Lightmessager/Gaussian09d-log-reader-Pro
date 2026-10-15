# G4 遗留修复与验证

日期：2026-10-15。G4 图表修复已验证；静态导出原生崩溃未根治，不能宣布 G4 全部完成。用户随后明确要求暂不继续底层排查、继续开发，已用临时方案完成 G5；这覆盖之前的阶段阻塞约束，不代表关闭 G4 根因。以下历史结果需与文末最新诊断及 docs/g5-validation.md 一起阅读。

## 修复内容

- WebEngine 加载：受限进程中无法可靠启动 Chromium 子进程或读取系统字体；正常桌面权限下本地页面成功加载，中文/希腊字形正常。未关闭 Chromium sandbox，也没有放开远程访问。加载日志增加状态名称，明确区分 `LoadStartedStatus/code=0` 与 `LoadSucceededStatus/code=200`。
- 3D 选中描边：scatter3d 不接受逐点 `marker.line.width` 数组，改为合法标量，继续以点尺寸和紫色边缘强调选择，保留项目路径本色。真实 Plotly 参数验证不再报告这一非法值。
- 放大与还原：Qt 重设 WebEngine 父窗口时不一定触发浏览器 window resize。新增帧合并的 ResizeObserver 重排，与 Plotly.react 串行执行；实际图表尺寸匹配容器，复用原浏览器，相机保持不变。
- 独立主题：同步原生后备图与 WebEngine 页面的底色；离线 HTML 正文、控件、表格边界、警告与悬浮框使用当前主题。
- 3D PNG：临时捕获显示模式包含完整轴标题、单位及 TS 标签，不继承紧凑面板隐藏标题的布局。成功或超时后恢复界面语言和实时布局，保留相机；临时标记不写入项目视图状态。
- 导出诊断：辅助进程失败时记录退出码，避免空 stderr 隐藏原生进程异常；没有增加自动重试或伪造成功状态。

相关代码为 `ui/profile_view.py`、`resources/plot/profile.js`、`profile.html`、`services/plot_export.py`；增加了主题后备与捕获超时恢复测试，以及 `tools/check_glass_g4.py`。没有修改科学求值、来源指纹、路径颜色或 SQLite schema。

## 已通过的检查

在原 `.venv` 中运行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='D:\Project\GaussianReadPro\src'
.\.venv\Scripts\python.exe -m pytest tests/test_plot_spec_export.py tests/test_workbench.py -q
```

结果：**43 passed in 44.43s**。其中图表/导出 18 项、工作台 25 项，覆盖 PNG/SVG/PDF/HTML 内容与清单、来源变化、主题后备以及捕获超时后的语言/布局恢复。Node 脚本语法检查与相关 Python 编译检查通过；没有重跑 S7 历史全量套件。

正常桌面权限下，最终真实 Qt/WebEngine 检查为 **8 项通过**：路径与图例颜色、独立主题、scatter3d/浏览器复用、尺寸/相机保持、真实 3D PNG、PNG 轴标题与视图恢复、HTML 清单、离线 HTML 主题与 3D 切换。无 JS 控制台错误，无远程请求。

历史 WebEngine 专项报告：`artifacts/ui-glass/g4/runs/73921e2528884e039649b9b39e9f0f62/validation.json`。报告明确记录 `static_exports=not_run`，不会把纯 WebEngine 验收混算为 Agg 稳定性通过。根目录 `validation.json` 只保留最新成功运行，不能替代各次历史证据。

最终桌面检查使用现有系统 Python 3.13.15，读取原虚拟环境中的 ABI 兼容 PySide6 6.12.0；没有替换虚拟环境或安装依赖。可在正常桌面使用以下命令复现图表专项：

```powershell
$env:PYTHONPATH='D:\Project\GaussianReadPro\src'
& 'C:\Users\16008\AppData\Local\Programs\Python\Python313\python.exe' -u -c "import sys; sys.path.append(r'D:\Project\GaussianReadPro\.venv\Lib\site-packages'); sys.path.insert(0,r'D:\Project\GaussianReadPro\tools'); import check_glass_g4; check_glass_g4.main(include_static=False)"
```

常规命令 `.venv\Scripts\python.exe tools\check_glass_g4.py` 默认包含全部 Agg 导出；`--skip-static` 只运行 WebEngine 专项并显式记录未运行项。各次运行使用隔离的合成项目、偏好及恢复目录，不使用用户工作项目。

已人工检查的截图位于 `artifacts/ui-glass/g4/`：

- `profile-web-2d-cn-light.png`：浅色中文比较图，正常系统字体。
- `profile-web-2d-en-dark.png`：浅色应用中的独立深色图表。
- `profile-web-3d-expanded.png`：重排后的放大三维窗口。
- `profile-html-dark.png`：离线 HTML 深色文字与控件。
- `profile-export-3d.png`：真实 WebGL 捕获，完整轴标题与单位。

## 仍需复验的运行环境问题

正常桌面 Agg 子进程复验中出现过 `0xC0000005` 访问冲突；Windows 事件日志也记录了 Python DLL 与 Codex 附带 PowerShell/coreclr 的原生崩溃。系统 Python 3.13 的独立子进程仅执行 `import matplotlib.figure`，不加载本项目或 Qt，6 次结果分别为访问冲突、Python 异常、Python 异常、成功、成功、成功。这证明该失败可独立于本次 UI 代码复现，尚不能归因于单一解释器或字体。

初次完整桌面运行 `runs/d1945818850b4747b26c12a8dff1a6e5/` 曾通过全部格式，但随后的失败不能用首次成功覆盖。失败报告保留在其他运行目录，例如 `runs/3ac7c81b661641bc86d34b7eb980098f/validation.json`，其中包含辅助进程退出码和导入阶段故障栈。须在 G4 解决或明确处理这一问题；没有为绕过异常修改绘图算法、关闭沙箱或改变正式依赖版本。

仅验证 Windows 当前桌面缩放；macOS/Linux、100%/150%/200% DPI 矩阵、完整性能及打包验收仍按 G6/S8/S9 执行。本次未进入 G5 或 S8。

## 最新诊断：原生崩溃与逻辑处理器 6 强相关

用户截图为 Python 原生空指针读取错误。截图本身没有故障模块名，不能直接认定 UI、Matplotlib 或 CPU 硬件损坏。

`tools/diagnose_static_runtime.py` 不导入本程序或 Qt，每次启动全新 `python -I -X faulthandler`，仅导入 `matplotlib.figure`。在原 `.venv`（Python 3.12.14、Matplotlib 3.11.2）执行 `--cpus 4,6,7,16 --rounds 10` 的结果：

| 进程允许的逻辑处理器 | 成功 | 失败 |
| --- | ---: | ---: |
| 默认全部处理器 | 9 | 1 |
| 4 | 10 | 0 |
| 6 | 3 | 7 |
| 7 | 10 | 0 |
| 16 | 10 | 0 |

完整证据：`artifacts/ui-glass/g4/static-runtime/b25aebf368014a10bcc66053e785d653/diagnostic.json`。CPU 6 的失败包括访问冲突、整数除零和 Python 正则引擎内部错误。Windows 拓扑显示 6、7 属于同一物理核心。更早逐核对比中 CPU 6 也有 2/3 次访问冲突，其他受测核心通过。该关联很强，但尚未确定 CPU、固件/电压设置、运行时或其他底层因素中的最终责任方。

单独放入 artifacts 的 Matplotlib 3.10.9 候选包也有 1/24 次正则引擎内部错误，不能证明降级解决问题；没有修改 pyproject、正式虚拟环境或锁文件。该候选仅用于对比，不参与生产运行。

软件侧已加固私有静态导出进程：隔离启动参数 `-I`、显式 Agg、独立配置目录、退出码/故障栈记录；Windows helper 使用进程局部错误模式，避免原生错误弹窗阻塞导出，失败仍上报。增加环境污染隔离与原生失败不重试/清理测试。这些措施没有根治默认调度下的崩溃，不能当作根因修复。

## 临时绕行与复验条件

新增 `run_app_compat_windows.cmd`，仅针对本次诊断的 32 线程 Windows 机器。用 Windows `start /affinity FFFFFF3F` 在 Python 启动前排除逻辑处理器 6、7；仅影响启动的程序及继承该限制的子进程，关闭程序即结束，不改变系统/BIOS。原跨平台入口保持不变。`start /affinity` 的含义见 [Microsoft 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/start)。该启动器是临时本机方案，不能作为三平台默认配置或硬件修复。

同一亲和性下的回归结果：**45 passed, 1 warning in 57.50s**。警告是旧 `.pytest_cache` 写权限，不是测试失败。第一次尝试被旧系统 pytest 临时目录权限阻断（43 个 setup errors），改用工作区全新 `--basetemp=artifacts/ui-glass/g4/pytest-25b6496b4b0443c5b2aeb85c75965a3d` 后全部通过。此前默认亲和性的一轮导出测试仍有 PNG/PDF 原生失败，不能用本次通过覆盖。

真实 Qt 连续检查使用原 `.venv`、正常桌面权限及 Chromium sandbox，通过同样的 `start /affinity FFFFFF3F` 启动 `tools/check_glass_g4.py --static-rounds 20`。报告记录 `process_affinity` 和每次独立导出的元数据；不重试、不使用 `--skip-static`。结果见下方本次运行记录。默认调度下的稳定性尚未关闭，因此 G4 仍不能标记全部完成。

本次运行 `artifacts/ui-glass/g4/runs/c3a3d30be5e54710b0013ef19faad6dd/validation.json`：**10 项桌面检查通过；20 轮、60 次全新 PNG/SVG/PDF 导出全部成功**，中英文交替，包含白底、单位、来源清单、文件哈希、完整 PDF/SVG、数值未变检查。`static_exports=included`、`process_affinity=0xffffff3f`，无 JS 错误或远程请求。本轮实际查看了 `profile-web-3d-expanded.png` 和 `export-2d-png/profile.png`，字体正常，轴与单位完整。根目录 `validation.json` 已更新为本次条件性通过报告。

下一步：确认本机是否存在降压/超频或其他程序异常，再决定如何进一步定位运行环境；未取得确定结论前保留临时启动器与默认入口的区别。没有修改系统设置，没有进入 G5/S8。

## 用户确认恢复默认后的复验

用户确认此前降压/超频已恢复默认，同时报告《杀戮尖塔2》也会闪退。这里只记录用户反馈，未读取调校参数，未确认游戏故障与 Python 故障属于同一原因。

随后原 `.venv` 再运行 `tools/diagnose_static_runtime.py --cpus 4,6,7,16 --rounds 10`：默认全部处理器 **10/10 成功**；CPU 4、7、16 各 **10/10 成功**；CPU 6 **6/10 成功、4/10 失败**（三次访问冲突、一次原生异常退出 3221226505）。完整报告：`artifacts/ui-glass/g4/static-runtime/c417efc48e964e4ca19b40dde6059b2b/diagnostic.json`。这说明用户确认恢复默认后仍可复现，不能仅以之前的降压/超频解释当前状态，也不能将默认调度的有限成功样本说成已稳定。

只读设备信息为 LENOVO 82WK，BIOS KWCN54WW，日期 2025-10-22；没有修改 BIOS、驱动或系统设置。建议下一步使用厂商官方硬件诊断并将上述逐核对照证据交售后分析；目前不能断言 CPU 已损坏或与桌面处理器的已知故障同源。保持 G4 未全部关闭。
