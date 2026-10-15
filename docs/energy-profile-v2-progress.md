# 能量剖面图 V2 进度

状态：EP1–EP6 已完成；2026-10-15 按用户 demo 要求完成 D038 视觉更新并复验。设计、阶段边界、验收和交给低成本模型的提示词见 `ENERGY_PROFILE_V2_PLAN.zh-CN.md`。二维和三维参考图位于 `design/`。

## EP1：容器、路径显隐和响应式主题

完成项：

- `ProfilePanel` 工具栏改为分组玻璃面板，宽度较小时使用紧凑标签；路径显隐菜单显示路径颜色，并遵守当前图表 kind/mode 与项目路径可见状态。
- 路径显隐按钮有中英文可访问名称、提示和键盘入口。切换只更新现有 `plot_state.hidden_paths` 与 `compare`，不更改节点、路径定义或计算结果。
- `QToolButton` 补充主题态样式；新增 CN/EN 文案。未改 Plotly trace 形状、科学计算或协议 2。

验证：

- `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_plot_spec_export.py tests\test_workbench.py -q`：47 passed（35.33s）。Windows 运行时沿用项目进程级兼容亲和性掩码 `0xffffff3f`；没有修改系统亲和性，也没有关闭 Chromium sandbox。
- `tools/check_energy_profile_ep1.py` 原生 Qt/WebEngine 验收通过：路径菜单、键盘触发、CN/EN、浅/深主题、宽/窄尺寸矩阵，以及显隐仅改变视图状态。报告：`artifacts/ui-glass/ep1/e5a39641e7f6432cba13a9a8d9ab43b1/validation.json`。
- 实际 Qt 截图（同一验收目录）：`paths-menu-cn-light.png`、`wide-cn-light.png`、`compact-en-dark.png`、`narrow-cn-light.png`、`narrow-en-light.png`。以上为 Qt/WebEngine 实际截图；本阶段没有验收 EP2/EP3 的图表视觉及 WebGL 交互。
- 不带兼容掩码的 pytest 启动发生 Windows 原生 access violation，与已记录的默认调度/运行时问题一致；因此不把无掩码运行记为通过。

未完成事项：二维读图进入 EP2；EP3 才处理三维交互。本次未验证 macOS/Linux 或发行包。

下一阶段入口：先读 `AI_HANDOFF.md`、本记录和 `ENERGY_PROFILE_V2_PLAN.zh-CN.md` 的 EP2，严格限于 EP2。

## EP2：二维能级、焦点和来源悬浮卡

完成项：

- Plotly 二维 hover 收敛为路径/节点、当前值与单位、适用模式下的绝对/参考能量，以及首个真实来源的名称、作业短 ID 和行号。表达式、SHA 与冗长诊断不再挤进悬浮卡；所有来自项目的文本转义后显示。
- 当前选中点使用主题的日落橙焦点环和向能量轴的点状投影线；相对/直接差值图的零线加粗，图内清楚注明虚线只作视觉引导。缺值仍由 Plotly 的 null 产生断点，不补零或插值。
- 局部势垒图上标记、工具栏按钮及双点差值文字根据 SCF、Gibbs 总自由能或 Gibbs 热校正使用 `ΔE‡`、`ΔG‡` 或 `ΔGcorr‡`；图上标注偏移改到默认点位右下方。直接差值标注保留 direct 说明。纸张静态导出沿用日落橙选中描边、显示选中点投影线并使用同一类势垒符号。
- PlotPayload 只新增双语展示文案和势垒符号，不改变 Hartree 值、路径参考、计算或协议 2。保留用户路径颜色与现有标签密度策略。

验证：

- `node --check src\gaussianreadpro\resources\plot\profile.js`：通过；Python `compileall`：通过。
- `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_plot_spec_export.py tests\test_workbench.py -q`：48 passed（39.77s），进程级掩码 `0xffffff3f`。
- `tools/check_energy_profile_ep2.py`：原生 Qt/WebEngine 验收通过。四点 oracle 完全保持；hover 来源内容紧凑且 `<script>` 标签以文本安全转义；WebEngine 实际 hover 卡、焦点投影、势垒类型和中英文图注均通过。运行报告：`artifacts/ui-glass/ep2/121470ca1ca44973921b5b9a26ba0ce6/validation.json`。
- 实际 Qt 截图（同目录）：`wide-cn-selected-hover.png`、`cn-hover-card.png`、`cn-explicit-barrier.png`、`cn-barrier-callout.png`、`en-2d-profile.png`。其中 `cn-hover-card.png` 与 `cn-barrier-callout.png` 是实际 WebEngine 图表区域截图。
- 受限启动下 WebEngine 曾返回 `LoadFailedStatus`、错误码 0、无 JS 错误；正常桌面权限下重跑通过。仍使用进程级掩码，没有关闭 Chromium sandbox。测试仅覆盖 Windows 源码环境，不代表发行包、macOS/Linux 或 EP3 WebGL 已验收。

未完成事项：EP3 三维路径分层、投影线、弱零平面和相机交互尚未实现；EP4–EP6 亦待后续阶段。

下一阶段入口：先读 `AI_HANDOFF.md`、本记录及 `ENERGY_PROFILE_V2_PLAN.zh-CN.md` 的 EP3，只执行 EP3。

## EP3：三维路径分层和相机交互

完成项：

- 三维图使用路径类别作为 Y 轴、反应步骤作为 X 轴、当前能量值作为 Z 轴；每条路径独立着色，Y 轴显示实际路径名。单路径时提示深度编码的是路径类别，多路径时更便于比较。不同路径参考体系仍显示明确警告。
- 增加低透明度 `z=0` 基准面和落到零平面的点状投影。基准面与投影线均跳过 hover，不抢占真实反应节点的提示与选择；没有引入连续势能面，也没有改变 Python 能量数值。
- 三维工具栏增加等轴测、路径正视、俯视、恢复已保存相机，以及旋转/平移模式。相机状态沿用现有 `viewports` 状态随项目保存；WebGL 不可用时回退到二维并给出提示。
- 只增加渲染层辅助 trace 和显示文案，协议仍为 2；离线 Plotly、路径定义、参考能量和科学计算语义保持不变。

验证：

- `node --check src\gaussianreadpro\resources\plot\profile.js`、相关 Python `compileall`、中英文 locale JSON 解析：通过。
- `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_plot_spec_export.py tests\test_workbench.py -q`：49 passed（46.41s），进程级亲和性掩码 `0xffffff3f`。
- `tools\check_energy_profile_ep3.py`：真实 Windows Qt/WebEngine 通过。检查单/双/三路径图层、不同参考提示、相机预设及状态持久化/项目重开（校验重开后 Plotly 场景实际应用相机）、Plotly WebGL 节点选择事件桥、12 次重复刷新后 trace 数固定为 13 且只绑定一组监听器、3D PNG 与离线 HTML 导出、强制无 WebGL 时回退到二维。最终报告：`artifacts/ui-glass/ep3/7f7fc7ef410b4b069844ba6107125fb6/validation.json`；JS 错误、远程请求和运行错误均为 0。
- 实际 Qt/WebEngine 截图：`artifacts/ui-glass/ep3/7f7fc7ef410b4b069844ba6107125fb6/single-path-3d-expanded.png`、`three-paths-en-3d.png`、`camera-presets-en-3d.png`、`reopened-saved-camera-3d.png`；静态图导出：`export-3d-png/profile.png`。已人工查看展开的单路径图及多路径 PNG 导出。
- 验收在 Windows 源码环境进行，进程使用 `0xffffff3f` 兼容掩码；未修改系统亲和性、未关闭 Chromium sandbox。交互测试验证了实时相机预设、旋转/平移模式及 Plotly 节点选择事件桥；选择测试通过注入 Plotly click 事件检查节点 ID 往返，没有单独自动化真实鼠标拖动或 WebGL 命中坐标。macOS/Linux 和发行包尚未测试。

未完成事项：EP4–EP6 后续阶段待实施；本阶段没有启动 S8。

下一阶段入口：先读 `AI_HANDOFF.md`、本记录及 `ENERGY_PROFILE_V2_PLAN.zh-CN.md` 的 EP4，只执行 EP4。

## EP4：选中节点详情与二维小概览

完成项：

- 图表选中节点后，右侧显示只读摘要、对应的小型二维能量概览，以及数值/参考能量的来源文件、作业序号和日志行号；已有可编辑节点属性仍保留在独立区域。
- 详情按 `project_id / revision / path_id / result_id / node_id / entry_id` 精确匹配，避免同名节点串选。草稿、失效、待计算、来源不可用和直接差值模式按规则隐藏不适用的绝对能量或参考能量，不展示过期/伪造值。
- 宽窗右侧详情可滚动；窄窗提供独立“节点详情”页签和整宽布局。小概览通过节点 ID 将点击选择回传到主工作区。增加中英文详情文案。

验证：

- `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_plot_inspector.py tests\test_workbench.py tests\test_plot_spec_export.py -q`：53 passed（48.79s），Windows 进程级亲和性掩码 `0xffffff3f`。
- Python `compileall` 与 `src/gaussianreadpro/resources/locales/zh_CN.json`、`en_US.json` JSON 解析：通过。
- `tools/check_energy_profile_ep4.py`：真实 Windows Qt/WebEngine 验收通过。六项检查全通过：选中值与来源定位、同名节点身份隔离、小概览按 ID 选中、展开图保留、紧凑详情页布局、中英文文案。最终报告：`artifacts/ui-glass/ep4/61bd52f249004987b5580363aabd016c/validation.json`。
- 实际截图：`wide-selected-node-inspector.png`、`expanded-energy-profile.png`、`compact-node-details.png`。人工检查紧凑截图确认摘要/小概览/证据可读，内容超出时可滚动。
- 仅验证 Windows 源码环境，使用进程级 `0xffffff3f` 掩码；未改系统亲和性或 Chromium sandbox。macOS/Linux 与正式发行包未测试；本阶段没有改变科学计算、数据库或协议 2，也没有进入 S8。

未完成事项：EP5 视图状态持久化与离线导出验收、EP6 综合验收与交接待实施。

下一阶段入口：先读 `AI_HANDOFF.md`、本记录及 `ENERGY_PROFILE_V2_PLAN.zh-CN.md` 的 EP5，只执行 EP5。

## EP5：视图状态持久化与离线导出

完成项：

- 验证图表模式、路径比较/显隐、图表主题、2D 视口范围及 3D 相机沿用 `plot_state` 保存，并在项目重新打开后恢复；未增加数据库字段或变更协议 2。
- 只读项目可以在当前会话切换视图和路径显隐；只读视图状态保存在面板内存中，不标脏项目、不写回项目文件。
- 通过真实 UI 导出 2D PNG/SVG/PDF/HTML 与 3D PNG/HTML。每个导出包的 manifest 文件清单及 SHA-256 均复核；2D 和 3D 独立 HTML 在 Qt WebEngine 中从本地资源成功绘图，CSP 禁止外连。
- 来源日志在绘图后发生变化时，导出拒绝并且不留下部分目录；已存在的导出目标会被拒绝，目录内容不变。

验证：

- `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_plot_spec_export.py tests\test_workbench.py -q`：49 passed（55.87s），Windows 进程级亲和性掩码 `0xffffff3f`。
- `tools\check_energy_profile_ep5.py`：真实 Windows Qt/WebEngine 专项验收通过。八项检查通过：2D 四种格式、3D 两种格式、2D/3D 离线 HTML 实际绘图、已有目标保护、来源变更拒绝、模式/显隐/主题/相机重开恢复、只读项目仅会话探索。运行报告：`artifacts/ui-glass/ep5/e9f8b518ca044d44bb5fe202a33dc91e/validation.json`。
- 截图：`energy-profile-2d.png`、`energy-profile-3d.png`；导出实物：`2d-png/profile.png`、`2d-svg/profile.svg`、`2d-pdf/profile.pdf`、`2d-html/profile.html`、`3d-png/profile.png`、`3d-html/profile.html`，均位于上述验收目录。人工查看了 2D/3D 实际 Qt 工作区截图及 PNG 导出。
- 验收仅覆盖 Windows 源码环境，使用进程级掩码 `0xffffff3f`；未更改系统亲和性或 Chromium sandbox。macOS/Linux、正式发行包和跨平台离线文件打开尚未测试；本阶段没有启动 EP6 或 S8。

未完成事项：EP6 综合验收、性能记录和最终交接待实施。

下一阶段入口：先读 `AI_HANDOFF.md`、本记录及 `ENERGY_PROFILE_V2_PLAN.zh-CN.md` 的 EP6，只执行 EP6。


## EP6：综合验收、demo 视觉对齐和最终交接

2026-10-15 完成。用户要求覆盖早期水平能级取舍（D038）：默认改为平滑多层高光曲线、圆形节点、橙色选中光环、3D 半透明光带/零面投影幕；整高图表、独立节点表页签和可收起的放大详情。Qt 小概览、离线 HTML、Matplotlib 静态导出共用显示几何，科学节点及求值不变。修复真实 WebGL 相机持久化竞争和窄窗多路径标签重叠。

验证：全量 273 passed（68.29s）；JS 语法、Python 编译及 359 键 CN/EN 对齐通过。最终原生套件 EP2/EP3/EP4/EP5、EP6 DPR 1/1.5/2 共 7/7 通过，源码哈希在套件期间不变；60 张实际 Qt 截图。真实鼠标 2D 节点选择、3D 拖动、六种导出、中文 PDF/SVG 实际渲染、离线页面、恢复和只读状态均复验。2D/3D 各 100 次更新约 4.7s，21/34 条 trace、五类监听器数量恒定；记录 UI 和 WebEngine private bytes 的完整样本。

完整报告及确切命令、源文件、原始结果、内存范围和失败修复记录见 [ep6-validation.md](ep6-validation.md)。最终套件：`artifacts/ui-glass/ep6/suite-8f82c87c0e1b425cb6709b3651b9de50/validation.json`；代表截图：`artifacts/ui-glass/ep6/final/`。

限制：仅 Windows 源码、进程亲和性 `0xffffff3f`；G4 默认调度问题仍未关闭，未继续底层排查。未验证 macOS/Linux、发行包、大规模真实日志及 GPU 显存，无改版前可比性能基线。EP6 已完成；S8/S9 没有启动。历史各阶段“待实施”仅记录当时状态。后续维护先读 AI_HANDOFF、D038 与本验收报告；S8 需用户明确启动。
