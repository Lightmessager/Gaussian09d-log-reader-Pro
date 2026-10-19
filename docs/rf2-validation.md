# RF2 外框、页面布局与统一工具栏验收

2026-10-17，RF2 源码阶段完成。图形仍使用 Plotly.js scatter3d 过渡 renderer；Three.js、方向立方体交互、真实分子和完整右栏数据分别属于 RF3/RF4。

## 修复与实现

- 上轮将 1442×951 的窗口截图当成桌面可用尺寸，错误地认为目标画布无法运行。独立验收程序现在直接启动当前源码，记录模块绝对路径、PID、资源 SHA-256、实际 DPR 和内容尺寸，避免混用旧窗口/EXE。
- 修复隐藏相机/主题控件缺少父组件、刷新时重新显示的问题。次要选项保留在菜单中。
- Qt 外框为 50 DIP 顶栏和 196 DIP 连续侧栏。导航按参考图顺序排列；RF8 模块各有独立路由及未实现提示。源文件及原路径/节点编辑保留在项目菜单中。
- 能量页内部使用一个 WebEngine 页面；`replica.css` 的 Grid 统一管理主工具栏、主图区、详情占位、方向占位及底部工具栏。能量页去除旧 Qt 页签、参数行、Qt 详情栏及 Plotly modebar。
- Qt/网页共用 `profile_themes` light/dark tokens；本地 SVG 图标及 CSS 随包配置已补齐，没有在线依赖。
- 网页操作沿用 project_id/revision/render_id 校验。2D/3D、路径、比较、重置和导出入口调用现有逻辑。放大模式使用同一完整页面，避免附加第二份 Qt 详情栏。
- 系统窗口操作继续使用原生标题栏。截图为应用内容区，不含原生标题栏。

## 真实 Qt/WebEngine 验证

命令：`.venv\Scripts\python.exe tools\check_profile_replica_layout.py --keep-open`。

报告：[validation.json](../artifacts/rf2/validation.json)。窗口标题具有 `[RF2 source · PID …]` 标识；使用独立 preferences/recovery 和 RF0 项目副本。验收进程设置 `QT_SCALE_FACTOR=0.8`，实际测得 DPR=1，未修改系统显示设置。沿用项目已有的进程亲和性兼容配置 `0xffffff3f`，不代表默认调度问题已解决。

坐标以 1672×941 DIP 内容区左上角为原点；Qt 外框读取实际组件 geometry，网页读取实际 DOM boundingClientRect 并加一次 WebEngine 原点 `(196,50)`。

| 区域 | 实测 x / y / w / h | 相对规格最大误差 |
| --- | --- | --- |
| 顶栏 | 0 / 0 / 1672 / 50 | 0 DIP |
| 侧栏 | 0 / 50 / 196 / 891 | 0 DIP |
| 主图列 | 208 / 59 / 1056 / 871 | 0 DIP |
| 顶部工具栏 | 216 / 69 / 1035 / 49 | 0 DIP |
| 右栏 | 1272 / 59 / 387 / 854 | 0 DIP |
| 方向占位 | 216 / 747 / 150 / 155 | 0 DIP |
| 底部工具栏 | 477 / 854 / 441 / 56 | 0 DIP |

通过项：只有一个 QWebEngineView、旧工具栏/页签隐藏、标准画布右栏无滚动；真实 WebEngine 按钮切换 2D→3D、隐藏/恢复 B、开关比较；科学显示值不变；分析导航路由独立；CN/light 1440×900 可运行；JavaScript 错误列表为空。实际运行 Plotly.js 版本为 4.1.1。

原始截图由可见 Qt 窗口的 `QWidget.grab()` 获取，包含实际 WebEngine 内容，未合成或缩放：

- [EN/dark，1672×941，DPR=1](../artifacts/rf2/rf2-en-dark-1672x941.png)
- [CN/light，1440×900，DPR=1](../artifacts/rf2/rf2-cn-light-1440x900.png)

源码回归：`tests/test_workbench.py`、`tests/test_glass_preferences.py`、`tests/test_plot_spec_export.py`、`tests/test_plot_inspector.py`，最终 **69 passed in 63.71s**。测试及子进程沿用上述亲和性配置；中途未加配置的 PDF helper 曾发生既有 G4 原生崩溃，本轮未扩展底层排查范围。

## 阶段边界

分子、双路径概览、关键能量表、方向立方体明确保留 RF3/RF4 占位。Zoom/Fit 完整行为留给 RF5，目前禁用并标明阶段。主图仍有旧 renderer 的相机/文字/材质差异，交给 RF3；完整窄窗抽屉和高 DPI 矩阵交给 RF5。RF2 未构建新 Windows EXE；现有发行包仍是 RF0 旧包，最终源码/包验收属于 RF7。

只完成 RF2，至此停止；下一阶段由用户指定。
