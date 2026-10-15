# S7 验收记录

2026-10-15，Windows / Python 3.12.14 / PySide6 6.12.0 / Matplotlib 3.11.2 / Plotly.js 4.1.1（从 Plotly Python 7.1.0 提取）。真实计算结果接入离线交互图与可追溯导出；SQLite v1、核心求值器与原始脚本保留。

## 使用方式

反应路径页默认二维水平能级，虚线仅作视觉引导。悬浮含完整标签、体系能量、差值、单位、参考、表达式、作业/行号、源指纹和诊断。点击联动节点表，表格选择反向高亮；Ctrl/Shift 点选或二维框选两个节点查看 Python 计算的能量差。只有第二点已指定 TS、第一点是相邻前驱，点击 ΔE‡ 才创建局部势垒。

二维支持平移、滚轮缩放、框选/套索和标签文本拖动；只修改像素偏移，不能修改能级。3D 为 scatter3d，可旋转/缩放，y 轴明确是路径类别，图例编号对应刻度；不创建连续势能面。WebGL 不可用明确提示并切回二维；页面加载失败回到原生预览。

比较路径统一使用当前单位，只纳入同类型/模式。不同参考明确提示各自零点并禁用跨路径差值。图表主题可跟随界面或独立设置。重置视口右键菜单可重置标签、清除势垒或显示全部路径。放大复用同一 WebEngine。视口按项目/路径/单位/类型/模式及 2D/3D 保存；相机、隐藏图例、标签、比较和主题随项目恢复。

导出选择格式、独立 CN/EN 语言和新结果目录：二维 PNG/SVG/PDF 默认白底 Matplotlib 图，三维仅 PNG/交互 HTML。每包附 data.csv、sources.csv、plot.json、manifest.json，包含公式、参考、UUID、常数版本、Hartree、来源路径/作业/行号/SHA 和输出哈希。HTML 附 assets，必须复制整个目录；无需 Qt bridge 或 CDN。CSV 文本防表格公式注入，JSON 保留原文。

## 验证与证据

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests\test_plot_spec_export.py -q
.\.venv\Scripts\python.exe tools\check_s7.py
```

全量 245 项通过（76.71 秒），S7 新增 15 项；最终布局调整后重跑相关 15 项。覆盖当前修订/身份/来源、无效草稿与空缺、单位、不同参考、显式 TS/前驱、视图白名单、四种格式/哈希、恶意 HTML/CSV 文本、已有目录与失败清理、三维格式、事件/恢复及导出前来源变更。无效参考草稿显示当前原文，不能展示最后有效 AST 作为当前参考。

原生脚本使用独立临时偏好及 SYNTHETIC 日志。人工 oracle 为 [0, .024, -.008, -.025] Hartree；kcal/mol 约 [0, 15.06022738, -5.02007579, -15.68773685]。artifacts/s7/validation.json 中 15 项通过，errors、javascript_errors、blocked_remote_requests 为空：

1. 核心结果与图值一致。
2. QTest 真实鼠标经 Plotly/WebChannel 回到表格。
3. 表格反向高亮图。
4. 显式局部势垒。
5. Plotly 视口/标签事件持久化且科学值不变。
6. 双路径比较。
7. 二维 PNG/SVG/PDF/HTML 输出。
8. 无 Qt bridge 的离线 HTML，图例保留视口并切换真实 3D。
9. scatter3d、相机状态和 1600×1000 PNG 捕获。
10. 中英文、浅深色、放大及紧凑窗口。
11. 100 次更新保持 trace/SVG 数量和单次事件绑定。
12. 过期事件被忽略。
13. 模拟 WebGL 缺失后的说明与降级。
14. 保存恢复 plot_state。
15. 全新窗口重开恢复视口/相机。

截图位于 artifacts/s7：profile-2d.png、profile-3d.png、profile-en-dark.png、profile-expanded.png、profile-compact.png。导出 QA 副本为 export-2d.png/.svg/.pdf、export-3d.png。PDF 经 pdftoppm 渲染为 pdf-preview.png，检查中文、希腊字母、标签与图例。相同能量多路径的自动标签间距已加大，紧凑三维简化文字。引线拖动层曾遮挡真实点选，已禁止引线鼠标命中，保留文本拖动。

二维由后台启动纯 Agg helper，避开 Qt/shiboken 导入 Matplotlib 时大量源码扫描；没有在主线程绘图或修改第三方钩子。结果从私有暂存目录复制发布，继承目标目录权限；失败清理半成品。原生验收不覆盖用户项目或已有结果目录。

## 边界

仅 Windows 源码实测。Codex 受限进程不能可靠加载原生 WebEngine，验收需正常桌面执行权限；没有关闭 Chromium sandbox 或使用单进程绕过。offscreen 和历史 S4 检查使用原生后备，不能替代本次 WebGL 验收。

100 次更新仅检查结构/绑定，不是内存泄漏或大批量性能结论；S8 继续测吞吐、响应、连续内存与高 DPI。三维优先悬浮/选中标签，二维超过 40 点常显选中/TS 标签；可放大或隐藏路径。使用系统字体回退，Windows 中文已检查，其他平台字体待实测。S9 分别验收三平台生产包、Matplotlib helper/数据和 WebEngine 资源，S0 演示包不是生产发行包。

