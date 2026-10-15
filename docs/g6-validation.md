# G6 液态玻璃集成验收

日期：2026-10-15。**G6 在 Windows 正常桌面权限和进程亲和性 `0xffffff3f` 条件下完成。** 用户要求暂置的 G4 默认调度崩溃仍未根治；G6 的通过不代表默认调度、macOS/Linux 或打包分发通过。未进入 S8。

## 实现

- 反应路径工作台宽度低于 1024 逻辑像素时，路径节点表与能量图成为可切换的整高页签；宽窗恢复双栏和原分隔比例。窄屏工具栏保留完整 tooltip/可访问名称，能量类型和模式按窗口尺寸与语言动态显示简写，单位 `kcal/mol` 完整可见。
- 图表窄屏纵轴使用与 PlotSpec `kind` 相符的 ΔG/ΔE/热校正符号，并保留单位；修复了读取不存在的 `energy_kind` 导致 Gibbs 误写为 ΔE 的问题。二维比较、三维放大、视口与科学数值沿用现有协议。
- 英文宽屏侧栏以 “Paths” 显示路径入口，tooltip/可访问名称仍是 “Reaction paths”；能量表列使用完整的 `ΔG / kcal/mol` 等短标题，tooltip 保留全称。
- 来源导入失败行显示 “Import failed”。若持久化记录表明文件已读但没有能量字段，来源详情显示 “No energy fields were found”；原因根据已保存的状态、大小和 SHA 判断，不重新解析日志、不更改 SQLite v1。
- 只扩展直接相关的 Widgets、Plotly 展示、locale、回归测试与原生验收脚本；没有修改计算器、UUID、能量表达式或来源绑定语义。

## 实际检查

最终全量回归：原 `.venv` Python 3.12.14，`QT_QPA_PLATFORM=offscreen`，独立 basetemp，进程亲和性 `0xffffff3f`，**263 passed in 55.30s**。JavaScript `node --check`、两份 locale JSON 解析和相关 Python `py_compile` 均通过。真实桌面验收运行 `tools/check_glass_g5.py --stage g6 --expected-dpr 1.25`，报告 `artifacts/ui-glass/g6/9c0aba31f30c496cbe7b25cf84786745/validation.json`：9 组检查通过，无 controller/JS 错误；包括 Gibbs 双语轴标题、窄屏页签、100 次真实图表更新、3D 与放大、失败来源、偏好排队保存和重启恢复。Chromium sandbox 保持启用。

最终代码又在以下进程级 Qt 缩放下完成同一原生脚本，报告均为 `passed=true`、9 组检查通过：

| `QT_SCALE_FACTOR` | Qt 报告 DPR | 验收报告目录 |
| --- | ---: | --- |
| 0.8 | 1.0 | `artifacts/ui-glass/g6/d02ee11b1c414745b7927cfb6c157b8c/` |
| 1.2 | 1.5 | `artifacts/ui-glass/g6/da56ef6b8c9d45f0888a7e457708cef0/` |
| 1.6 | 2.0 | `artifacts/ui-glass/g6/adaff47744914c79a2d052e8d39981c8/` |

本机系统原生缩放为 125%；表中 100%/150%/200% 是当前 Windows 桌面上的**进程级 Qt 缩放模拟**，未改系统 DPI。真实 Qt 截图均由当前程序窗口 `.grab()` 保存。人工检查了上述运行的窄屏二维图、宽屏英文深色页、英文深色紧凑页、3D 放大图与失败来源页：图轴和单位可读，主要操作可达，失败行与原因清楚。最终 125% 目录包含 1440×1000 中文浅色/英文深色、1100×820 英文减少效果、860×680 中英浅深紧凑、节点页、二维/三维、放大图、外观菜单、失败来源与重启弹窗，共 12 张截图。G3 的 `expression-components-cn.png`、`expression-error-en-dark.png`、`batch-preview-en-dark.png` 和 G4 的 `profile-web-2d-cn-light.png` 保留有效/无效表达式、批量预览与二维路径比较的真实 Qt 证据。

最终 125% 运行记录：QA 初始化至首图就绪 2.58 秒（含独立项目建立与四个合成日志导入，**不是纯冷启动**）；100 次节点选择触发 100 次图表更新共 3.31 秒，render count 11→111，监听器始终 1、trace 始终 3。Python UI 主进程工作集从 384,786,432 字节到 370,401,280 字节；1.20 秒空闲采样中该进程 CPU 时间为 0。**内存/CPU 数字不含 WebEngine 子进程，也没有改版前的可比基线**，不能据此推断总进程内存、FPS 或跨平台性能；完整负载与跨平台测量继续属于 S8/S9。

## 环境边界

先前四次 `profile.html` 的 `LoadFailedStatus` 来自受限工具运行环境，`errorCode=0` 且无 JS 错误。改用正常 Windows 桌面权限后，同一本地页面立即通过，随后多次 G6 原生验收与 DPI 矩阵通过；没有为掩盖失败而禁用 Chromium sandbox 或修改图表加载策略。失败记录仍保留在 `artifacts/ui-glass/g6/`。

所有 Windows 验收均使用只作用于本次 Python 进程的 `start /affinity FFFFFF3F`，排除本机逻辑 CPU 6/7。用户已要求暂不继续 G4 底层排查；这不构成硬件结论或默认调度稳定性证明。G6 已完成，下一阶段按总方案是 S8，尚未启动。
