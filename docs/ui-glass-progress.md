# 液态玻璃改版进度

状态：G1–G3、G5–G6 已完成；G6 通过 Windows 正常桌面权限和临时进程亲和性下的原生验收及 DPI 矩阵。G4 默认调度崩溃仍按用户要求暂置；下一阶段 S8，本轮未进入。日期：2026-10-15。

G1 建立薰衣草紫/落日橙主题 tokens、浅/深色 QPalette 与 QSS、可减少效果的 `GlassBackdrop`/`GlassPanel`，并新增本地 SVG 图标和独立 Qt 样板窗口。保留 `apply_theme(app, theme)` 调用及 bool 返回。主要实现位于 `src/gaussianreadpro/presentation/palette.py`、`src/gaussianreadpro/ui/theme.py`、`src/gaussianreadpro/ui/glass_widgets.py` 和 `src/gaussianreadpro/ui/glass_gallery.py`；资源打包配置已加入 JSON/SVG。

实际检查：运行 `.venv\Scripts\python.exe -m gaussianreadpro.ui.glass_gallery --output artifacts/ui-glass/g1`，原生 Qt 窗口成功生成 1180×800 浅色、深色和减少效果截图，三张均已人工查看。截图：`artifacts/ui-glass/g1/g1-light.png`、`g1-dark.png`、`g1-reduced.png`。确认文字/表格可读、紫橙配色符合方案、深色状态徽标有对比度，减少效果移除渐变并采用稳定实色面。

G1 阶段未运行 pytest，也未重跑 S7 历史 245 项测试/15 项原生验收；不据此宣称回归套件通过。该阶段验证仅为 Windows 原生 Qt 样板 1180×800，未覆盖生产工作台、DPI 矩阵、macOS/Linux 或安装包。G1 后续计划为 G2；当时未进入 S8。

G2 完成主工作台玻璃背景/卡片、顶栏和导航适配，紧凑宽度折叠导航与项目操作菜单；保留 64px 紧凑侧栏、172px 完整侧栏、快捷键、搜索与语言/主题入口。表格有效/警告文字颜色改读主题 token，行高统一为 34px；菜单标签补齐中英翻译。改动集中在 `ui/main_window.py`、`ui/tables.py`、`ui/theme.py`、两份 locale JSON，以及同步旧深色主题断言的 `tests/test_workbench.py`。

G2 原生 Qt 检查：1440×920 中文浅色首页、1100×820 英文深色来源页、860×680 中文浅色路径页；另用隔离副本加载 6 个来源/4 个节点，检查深色来源表、选中态/证据和浅色节点表/能量图。截图均在 `artifacts/ui-glass/g2/` 并已人工查看，紧凑导航图标完整。`QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe -m pytest tests/test_workbench.py -q`：25 passed。未测试 DPI/其他平台，未重跑 S7 全量验收；未进入 S8。

G3 完成表达式组分构建器、专家表达式、错误/括号高亮与批量编辑预览的玻璃分区布局。补齐新控件的 CN/EN 文案、可访问名称、目标计数和状态样式；批量编辑明确展示预览未应用，并将唯一主按钮用于应用。错误范围沿用原 Unicode/Qt 光标位置转换与解析结果，计算预览、自动草稿及应用语义未改。截图检查发现弹窗玻璃面板未随应用主题初始化，已让表达式和批量弹窗从当前 `glassTheme` 读取面板外观。

G3 检查：`QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe -m pytest tests/test_node_editor.py -q`：11 passed。保存了真实 Qt 对话框 `.grab()` 截图：`artifacts/ui-glass/g3/expression-components-cn.png`（中文组分编辑器）、`expression-error-en-dark.png`（深色错误态）、`batch-preview-en-dark.png`（批量预览成功态）。运行环境的字体缺少部分字形，截图中一些标签以方框显示，因此不把它作为中英文排版通过的依据；布局、错误危险色波浪线、预览输出及深色卡片均已检查。后续 G4 或专项 QA 应在具有完整字体的桌面环境补拍浅色批量截图。未测试 DPI/其他平台，未重跑 S7 全量验收；未进入 S8。

G4 将图表渲染配色集中为 profile payload 的可序列化 `visual_style`，由共享 lavender/sunset palette 生成；Plotly 的 2D/3D背景、网格、标签与选中态都读取该字段。选中节点改为紫色外圈/加大尺寸，路径本色保持不变；静态二维导出仍为白底，选中标记只增加紫色描边。原生后备图使用相同主题 token，TS 使用菱形，缺失点仍断线。改动位于 `ui/profile_view.py`、`resources/plot/profile.js`、`ui/profile_preview.py`、`services/plot_export.py` 和 `tests/test_plot_spec_export.py`；没有修改路径颜色或科研数据。

G4 首轮离屏检查通过 16 项图表/导出测试与 25 项工作台测试，但 WebEngine 本地页加载失败、系统字体不可读。后续以正常桌面权限复现：本地页加载成功，中文与希腊字符正常，确认之前的加载失败与方框字来自受限运行环境。保留 Chromium sandbox；加载诊断补记 LoadStarted/LoadSucceeded 状态，避免把 errorCode=0 当成加载结果。

G4 遗留修复：3D 使用合法的标量描边宽度；图表放大/还原通过串行 ResizeObserver 队列重排，保留相机；图表独立主题同步原生后备和 WebEngine 底色；离线 HTML 深色正文/按钮/表格与悬浮框同步；3D PNG 在捕获时显示完整轴标题、单位和 TS 标签，完成或超时均恢复实时布局与语言。相关回归 43 passed，真实桌面 WebEngine 专项 8 项通过；脚本 `tools/check_glass_g4.py`，最终报告 `artifacts/ui-glass/g4/validation.json`，截图 `profile-web-2d-cn-light.png`、`profile-web-2d-en-dark.png`、`profile-web-3d-expanded.png`、`profile-html-dark.png` 与 `profile-export-3d.png` 均已人工查看。详细证据及复现命令见 `docs/g4-validation.md`。

最新原生崩溃诊断：独立 Python 仅导入 matplotlib.figure，逻辑 CPU 6 失败 7/10，CPU 4、7、16 各通过 10/10；默认调度失败 1/10。证据见 `static-runtime/b25aebf368014a10bcc66053e785d653/diagnostic.json`。尚不能确定硬件/固件/运行时责任，不把关联说成硬件损坏。Matplotlib 降级候选也失败，正式依赖未改。

已隔离静态 helper 的 Python/Matplotlib 环境并保留错误诊断；这未根治默认调度崩溃。新增本机临时启动器 `run_app_compat_windows.cmd`，仅为程序进程排除逻辑 CPU 6、7，不改系统设置。此条件下回归 **45 passed**；真实 Qt 检查 **10 项通过，20 轮共 60 次 PNG/SVG/PDF 导出连续成功**，无重试。报告 `runs/c3a3d30be5e54710b0013ef19faad6dd/validation.json` 记录 `process_affinity=0xffffff3f`、`static_exports=included`；根报告同步。本轮二维导出与三维放大截图已实际查看。详见 `docs/g4-validation.md`。

G4 仍有默认启动稳定性问题，临时绕行通过不等于根因修复。用户确认调校已恢复默认，且游戏也闪退；随后复验 CPU 6 仍失败 4/10，默认全部及 CPU 4、7、16 各通过 10/10。新证据 `static-runtime/c417efc48e964e4ca19b40dde6059b2b/diagnostic.json`。恢复默认后仍可复现，尚不能确定底层责任方，建议厂商诊断；不进入 G5/S8，不推迟到 G6。其他平台/DPI 和 S7 全量未重跑。

G5：用户随后明确“暂不管这个、接着做”，覆盖上面的阶段阻塞约束；底层崩溃仍未关闭，未更改系统/BIOS。新增顶栏外观菜单及 CN/EN 两项偏好；完整旧 v1 键集只读补默认，缺字段/未知键/错误类型仍拒绝。选择经原 controller 排队保存，不改科研 revision。共享主题同步现有与新弹窗的实色材质；有限按钮复用 140ms 悬停/焦点、90ms 按下边缘过渡，隐藏即停，减少动效立即切换，无空闲动画循环。

G5 检查：偏好/存储/工作台/编辑器 65 passed，图表导出 20 passed。真实 Windows Qt 4 组专项检查通过，涵盖宽窄中英浅深色、排队保存、重启恢复与新弹窗继承；6 张截图已实际查看，见 `artifacts/ui-glass/g5/523e1e4ad64f47ae9272134229e13189/`。全部验证使用临时亲和性 `0xffffff3f`，不代表默认调度稳定；详细命令与限制见 `docs/g5-validation.md`。截图发现紧凑反应路径页图表高度不足、轴/提示挤压，列为 G6 优先修复，不计作完整窄屏布局通过。未进入 G6/S8，未跑全量/跨平台/DPI 矩阵。

G6 实施记录（2026-10-15）：窄窗（<1024）反应路径页切换为整高“路径节点 / 能量图”页签，宽窗恢复原双栏与分割比例；坐标轴及工具栏改为窄屏短标签，完整标签保留于 tooltip/辅助名称，能量类型切换时同步更新简称。实际截图检查旧版窄屏时发现轴标题错误显示 ΔE：PlotSpec 的真实字段是 `kind`，JS 原来读取不存在的 `energy_kind`；已修正为 `kind`，并在真实 WebEngine QA 中新增 Gibbs 相对能量轴标题（中英两种）断言。补齐中文目录缺失的“能量图”键。改动涉及 `ui/main_window.py`、`ui/profile_view.py`、`resources/plot/profile.js`、中英 locale、`tools/check_glass_g5.py`、`tests/test_workbench.py`。

最终 `pytest -q -p no:cacheprovider` 全量 **263 passed in 97.77s**（`QT_QPA_PLATFORM=offscreen`、独立 basetemp、进程亲和性 `0xffffff3f`）；`node --check src/gaussianreadpro/resources/plot/profile.js` 通过。此次全量首次发现中英文目录键差异，修复后复跑全量通过。

G6 首次四次原生尝试均在受限工具环境运行，`profile.html` 记录 `LoadStartedStatus → LoadFailedStatus`、errorCode=0、无 JS 错误；失败报告保留在 `artifacts/ui-glass/g6/fd24c14f4f384a26a16e895cb656f6d3/` 等目录。改用正常 Windows 桌面权限后，同一页面成功加载，说明早先失败是验收环境限制，不是已证明的应用层图表回归。

G6 最终验收：窄窗整高页签、动态简称与完整单位、双语 ΔG 轴标题、英文侧栏 “Paths” 和 ΔG 表头、失败来源原因、真实 3D/放大、偏好保存重开均通过。最终全量 **263 passed in 55.30s**；原生 Qt 9 组检查通过，报告 `artifacts/ui-glass/g6/9c0aba31f30c496cbe7b25cf84786745/validation.json`，12 张截图含 1440×1000、1100×820、860×680 中英浅深主题和失败态。最终代码在进程级 Qt DPR 1.0/1.5/2.0 也全部通过（目录 `d02ee11…`、`da56ef6…`、`adaff477…`）；截图已实际检查。100 次图表更新 3.31 秒，监听器保持 1、trace 保持 3；Python UI 主进程内存与空闲 CPU 见 `docs/g6-validation.md`，WebEngine 子进程和改版前基线未计。G6 完成；G4 默认调度问题仍未关闭，不推断跨平台/默认稳定。下一阶段 S8，本轮未启动。
