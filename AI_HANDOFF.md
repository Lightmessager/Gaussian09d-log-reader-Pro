# GaussianReadPro 后续 AI 入口

当前 S7 已完成：共享 PlotSpec、离线二维/三维交互图、表格选择联动、视口/相机/标签恢复、显式局部势垒与可追溯导出。全量 245 项测试、Windows 原生 15 项验收通过；见 docs/s7-validation.md、artifacts/s7/validation.json。S1–S6 科学核心、存储、公式编辑和 CN/EN 保留。启动：.venv\Scripts\python.exe tools\run_app.py。

能量图专项 **EP1–EP6 已完成**。2026-10-15 用户要求按 demo 还原高光曲线、圆形节点、橙色选中光环和 3D 面积虚影；D038 覆盖早期水平能级展示选择。现在默认整高图表，节点表独立页签，宽窗/放大图保留只读详情；小概览及导出同步。`curve_runs` 只作显示引导，科学节点/求值/CSV 不变。已修复实际 WebGL 相机保存竞争和窄窗标签密度。完整实现、命令、证据与限制见 `docs/ep6-validation.md`，方案/进度见 `docs/ENERGY_PROFILE_V2_PLAN.zh-CN.md`、`docs/energy-profile-v2-progress.md`。全量 273 passed；最终 Windows 原生套件 7/7 通过（含 DPR 1/1.5/2、实际鼠标点击与旋转、六种导出及恢复）。套件报告 `artifacts/ui-glass/ep6/suite-8f82c87c0e1b425cb6709b3651b9de50/validation.json`，实际截图 `artifacts/ui-glass/ep6/final/`。所有 Qt 验收用进程级掩码 `0xffffff3f`；macOS/Linux、正式发行包与默认调度稳定性未验证。G4 默认调度崩溃仍是已知限制，遵守用户要求暂不继续排查；S8/S9 未启动，需用户明确要求。

先读 docs/handoff.md；完整产品方案 IMPLEMENTATION_PLAN.zh-CN.md。液态玻璃 UI 专项 G1–G3、G5–G6 已完成；G6 完成窄窗整高图表/节点页签、动态双语短标签、准确 ΔG/ΔE 坐标轴、英文侧栏与表头及来源失败原因。最终全量 263 passed；真实 Windows Qt/WebEngine 9 组验收、12 张截图和进程级 Qt DPR 1.0/1.5/2.0 矩阵通过，报告 docs/g6-validation.md。先前受限工具环境导致本地页 LoadFailed，正常桌面权限立即通过，未禁用 Chromium sandbox。用户明确要求暂不继续底层崩溃排查、继续开发；G4 默认启动崩溃仍未根治。本机临时启动器 run_app_compat_windows.cmd 排除逻辑 CPU 6/7，只影响进程，不改系统设置；G6 的通过不能当作默认调度或跨平台稳定。下一阶段 S8，本轮尚未启动。遵守 docs/contracts.md v1.8、docs/decisions.md D033–D038。

目标：中英文、现代桌面 UI、清晰二维/三维能量剖面、逐节点公式构建、工作恢复、三平台分发。架构：Python + PySide6 Widgets/QSS + 本地 Plotly.js/QWebChannel + SQLite，Python 核心唯一计算源。二维静态图使用独立 Matplotlib Agg helper；原脚本保留。

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

