# GaussianReaderPro 后续 AI 入口

**当前任务（2026-10-18）：UX v2 U0–U8 已完成。** Windows x64 2.0.0 便携包全量构建；PE/ZIP/模块/资源审计 10/10；冻结 EXE 默认页新建、保存、改名及打开搭建器 7/7；Agg PNG/SVG/PDF 通过。WebEngine 本地页在源码与冻结版均失败，未宣称浏览器页面/3D 通过。ZIP SHA256 `d67ee20cdbc66f8e96dce3ebe70a8c9d177400dadef62f4ac90335811c132d00`，EXE SHA256 `e9fdc3e652835b92847d756130e7db1cee7f210eb3662ccdfbd9403192faa587`。报告与产物见 `docs/ux-v2-u8-validation.zh-CN.md`、`artifacts/releases/GaussianReaderPro-2.0.0-Windows-x64-portable.zip`。U8 聚焦回归 6 passed；没有运行单进程仓库全量测试。

**U7 历史状态（截至 2026-10-18 的 U7 完成时）：UX v2 U0–U7 源码阶段及本机路线验收已完成。** U0 基线及只读复核见 `docs/ux-v2-baseline.zh-CN.md`；U1–U6 分阶段实现与验收证据见 `docs/ux-v2-u1-validation.zh-CN.md` 至 `docs/ux-v2-u6-validation.zh-CN.md`。U7 通过回归修复了应用保存后草稿基线未刷新的问题；从默认首页的原生 UI 路线完成改名、导入/作业选择、两条不同颜色路径、反应物零点、预检/保存、含硼结构、能量图及 HTML 数据导出，并在新进程核对项目/路径 UUID、AST 摘要、零点、物种关系和图表。三份可追溯 Gaussian16 日志的 SHA、SCF 作业/行与保存重开通过；样本相对能量全为 0，不代表势垒。U7 的 87 项兼容分组、37 项草稿、14 项保存、13 项反应网络、38 项存储和 4 项真实日志回归通过，详细命令与退出码见 `docs/ux-v2-u7-validation.zh-CN.md`；总览见 `docs/ux-v2-validation.zh-CN.md`。本机 WebEngine 本地图表页面加载失败，但原生二维后备可见且正确显示数据；WebEngine/3D 与冻结包运行未验收（截至 U7）。随后 U8 已构建 GaussianReaderPro 2.0.0 并完成冻结包与 EXE 首页验收；当前 WebEngine 源码和冻结版仍报告 profile.html failed to load。工作区无 `.git`；没有运行单进程仓库全量测试。U5 曾记录的单进程 Qt 中止在后续已运行分组中未复现。

**当前追加（2026-10-17）：用户已启动 S8。** 真实 Gaussian16 三日志核心性能样本、合成项目连续科学流程测试、按文件组覆盖的 348 passed/1 skipped、正常桌面权限下原生 15/15，以及三日志真实 UI 流程（SCF 绑定、零点、图表、HTML 导出、保存/新会话恢复）见 `docs/s8-validation.md` 和 `docs/handoff.md`。真实三节点能量相同，非零势垒路径、单进程长回归、原生约 1000 行表格及 UI/WebEngine 内存/大文件负载仍未完成，因此 S8 未关闭。下文“未启动 S8”均为历史阶段记录。

**RF7 历史记录（2026-10-17）：RF7 已完成，产品改名 GaussianReaderPro、版本 0.2.0，已生成本地 Windows x64 便携包。全量 306 passed；源码/新 EXE 主链各 27/27，独立恢复与窗口/DPR 矩阵 43/43，EXE 导出文件搬移后的离线页与中宽布局检查 11/11，包审计 9/9。新 EXE 真实拖动 52.89 FPS，选择/详情 p95 33.5/75.7 ms；36 个包内资源与源码 SHA 一致。真实验收发现并修复了冻结 SVG/PDF 后端遗漏、长保存路径挤压按钮、1100 工具条文字越界/立方体遮挡及 tooltip 遮纵轴；诊断等待改为释放 GIL 的 QEventLoop，保留旧超标/失败记录。报告 `docs/rf7-validation.md`、综合证据 `artifacts/rf7/validation.json`。包 `artifacts/releases/GaussianReaderPro-0.2.0-Windows-x64-portable.zip`；入口 `dist/GaussianReaderPro/Launch-GaussianReaderPro-compat.cmd`，EXE SHA256 `4889b26df64fa8b1db4c1d6755b3ddab59fb8a97b102abfef5994e168ad8478d`。内部 Python 包及旧 QSettings/恢复目录保留兼容；SQLite v1 不变。仍用本机亲和性 `0xffffff3f`，不重查 G4，不宣称默认调度或跨平台稳定。当时停在 RF7，未发布远端 Release。**

**RF8/v.1.0 最新进度（2026-10-17）：RF8 源码完成，GaussianReaderPro v.1.0 Windows 便携包已构建。** 真实来源 SHA 校验/异步读取、结构可旋转预览与坐标导出、54 个 Gaussian16 谐振频率及热化学字段来源展示、项目结果筛选/CSV、按作业范围纯文本日志查看已实现。NBO 支持 Gaussian NBO 3.1 的 NPA/E(2) 表格，带搜索和来源行。IRC 已按真实 Gaussian16 双分支输出解析 forward/reverse、相对 TS 能量汇总和逐点 `CURRENT STRUCTURE`，Qt 表格选点切换结构，点坐标与汇总交叉核验。源码全量回归 317 passed。v.1.0 PE/资源/ZIP 审计 9/9；命令行版本正确。WebEngine 烟测在当前主机源码、冻结版及旧 0.2.0 包均报告本地页面加载失败，故该主机的浏览器运行验收未通过。发行包和证据见 `docs/v1-validation.md`。更早的 RF7/多路径段落是历史状态。

**最新追加（2026-10-17）：多反应路径与自定义颜色已完成源码实现。能量页顶部“+”打开真实创建弹窗，可选颜色/已有节点/顺序，或新建空路径；继承活动路径能量类型/单位/参考并开启比较。完整路径列表支持显隐、活动路径和按 UUID 改色，三条以上不再挤掉开关；沿用同一高光/面积阴影算法，新增路径自动更新构图尺度，多路径图例/表格可滚动。五路径/20 节点真实验收 22/22（PID 50840、45628），相关回归 48 passed；保存、新进程恢复与离线比较通过，JS/远程请求 0。见 `docs/multi-path-validation.md`、`artifacts/multi-paths/validation.json`。新增节点选择明确为共享节点，空路径可后续添加独立节点，不伪造能量。RF7/RF8、S8/S9 未启动，EXE 未重建。**

**最新任务（2026-10-17）：RF6 源码阶段已完成。选择/详情/抽屉与独立 2D、Three 相机状态接入保存恢复；3D PNG 使用当前 Three renderer，菜单区分仅图表与含详情的工作台展示图。离线 HTML 包含 Three/分子/许可，移动目录后 file:// 运行，无 Qt bridge；仅嵌入已核验的当前坐标，其他节点明确无嵌入结构。审计 CSV 与来源校验覆盖离线可揭示路径。真实 Windows 原生 31/31（PID 2492、42468），含独立进程重启、旧相机迁移、离线 Compare 往返、WebGL 降级与超时恢复；相关回归 45 passed，远程请求/JS 错误 0。报告/产物/命令见 `docs/rf6-validation.md`、`artifacts/rf6/validation.json`、`artifacts/rf6/run-b4f4796126/`。使用已记录亲和性 `0xffffff3f`，不重查 G4。停在 RF6；RF7/RF8、S8/S9 未启动，旧 Windows EXE 未重建。**

RF5 源码交付保留：2D/3D 交互、键盘节点访问、跨视图选择、路径比较与窄窗详情；DPR=1/1.5 原生各 19/19、40 项相关回归，见 `docs/rf5-validation.md`。RF0–RF4 历史证据见各阶段记录。

当前 S7 已完成：共享 PlotSpec、离线二维/三维交互图、表格选择联动、视口/相机/标签恢复、显式局部势垒与可追溯导出。全量 245 项测试、Windows 原生 15 项验收通过；见 docs/s7-validation.md、artifacts/s7/validation.json。S1–S6 科学核心、存储、公式编辑和 CN/EN 保留。启动：.venv\Scripts\python.exe tools\run_app.py。

能量图专项 **EP1–EP6 已完成**。2026-10-15 用户要求按 demo 还原高光曲线、圆形节点、橙色选中光环和 3D 面积虚影；D038 覆盖早期水平能级展示选择。现在默认整高图表，节点表独立页签，宽窗/放大图保留只读详情；小概览及导出同步。`curve_runs` 只作显示引导，科学节点/求值/CSV 不变。已修复实际 WebGL 相机保存竞争和窄窗标签密度。完整实现、命令、证据与限制见 `docs/ep6-validation.md`，方案/进度见 `docs/ENERGY_PROFILE_V2_PLAN.zh-CN.md`、`docs/energy-profile-v2-progress.md`。全量 273 passed；最终 Windows 原生套件 7/7 通过（含 DPR 1/1.5/2、实际鼠标点击与旋转、六种导出及恢复）。套件报告 `artifacts/ui-glass/ep6/suite-8f82c87c0e1b425cb6709b3651b9de50/validation.json`，实际截图 `artifacts/ui-glass/ep6/final/`。所有 Qt 验收用进程级掩码 `0xffffff3f`；macOS/Linux、正式发行包与默认调度稳定性未验证。G4 默认调度崩溃仍是已知限制，遵守用户要求暂不继续排查；S8/S9 未启动，需用户明确要求。

先读 docs/handoff.md；完整产品方案 IMPLEMENTATION_PLAN.zh-CN.md。液态玻璃 UI 专项 G1–G3、G5–G6 已完成；G6 完成窄窗整高图表/节点页签、动态双语短标签、准确 ΔG/ΔE 坐标轴、英文侧栏与表头及来源失败原因。最终全量 263 passed；真实 Windows Qt/WebEngine 9 组验收、12 张截图和进程级 Qt DPR 1.0/1.5/2.0 矩阵通过，报告 docs/g6-validation.md。先前受限工具环境导致本地页 LoadFailed，正常桌面权限立即通过，未禁用 Chromium sandbox。用户明确要求暂不继续底层崩溃排查、继续开发；G4 默认启动崩溃仍未根治。本机临时启动器 run_app_compat_windows.cmd 排除逻辑 CPU 6/7，只影响进程，不改系统设置；G6 的通过不能当作默认调度或跨平台稳定。下一阶段 S8，本轮尚未启动。遵守 docs/contracts.md v1.8、docs/decisions.md D033–D038。

目标：中英文、现代桌面 UI、清晰二维/三维能量剖面、逐节点公式构建、工作恢复、三平台分发。架构：Python + PySide6 Widgets/QSS + 本地 Three.js（3D 与离线 HTML）/Plotly.js（2D）/QWebChannel + SQLite，Python 核心唯一计算源。二维静态图使用独立 Matplotlib Agg helper；原脚本保留。

底层问题记录：用户确认降压/超频已恢复默认，另有游戏闪退。随后逐核复验 CPU 6 仍失败 4/10，默认全部及 CPU 4、7、16 各通过 10/10；证据 static-runtime/c417efc48e964e4ca19b40dde6059b2b/diagnostic.json。不能断言硬件损坏，不能以默认调度有限样本通过覆盖逐核失败。用户要求暂不继续排查；G4 根因未关闭。

关键约束：

- UUID、显示名和公式引用分离，禁止模糊匹配或同名覆盖。
- 节点体系能量只减路径参考一次；直接差值是独立模式。
- 内部 Hartree，SCF、Gibbs 热校正和总自由能严格区分。
- 保留作业/行号/SHA；缺值不补 0，无效草稿不显示旧有效值。
- worker 串行核查来源、计算和 I/O；事件检查 project/revision/render_id。
- plot_state/工作区存项目，本机语言主题存偏好；SQLite v1 不变，失败不能显示保存成功。
- TS 与相邻前驱须显式选择并点击才标局部势垒；3D y 轴为路径类别，不拟造势能面。
- 离线资源随包；三平台分别构建实测，Windows 源码通过不代表发行完成。

执行顺序：S0 原型 → S1 解析 → S2 公式 → S3 存储 → S4 UI → S5 CN/EN → S6 编辑器 → S7 图表 → S8 综合验收 → S9 发布。原方案模型建议：默认 gpt-6.1-sol，明确局部工作可用 gpt-6-luna，复杂疑难按需 gpt-6-astra；以实际环境可用性为准。

S8 注意：G6 已对 100 次图表更新记录结构、吞吐和 Python UI 主进程内存，并检查进程级 Qt 高 DPI；EP6 已补充 UI/WebEngine private bytes 与工作集样本、真实相机拖动和三档 DPR；GPU 显存、改版前可比基线、大文件与 macOS/Linux 仍未验证。真实日志覆盖需扩充。当前锁文件 requirements-s7-windows-lock.txt。S0 打包配置为历史演示，S9 须包括 Matplotlib helper/数据、生产页面与 WebEngine。复制路径共享节点、参考独立；100 步撤销不跨会话；构建器最多 40 行。详细代码入口、恢复边界和下一步见 docs/handoff.md。


