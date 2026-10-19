# 能量工作台参考图复刻进度（RF）

## 2026-10-17：RF8 源码完成：IRC 双分支真实样本已核对

移除 RF8 通用占位页，接入结构/振动/热化学/项目表格/日志查看器；NBO 支持 Gaussian NBO 3.1 的 NPA 与二阶 E(2) 表格，按来源行定位。IRC 现按明确的 forward/reverse、Path Number、汇总能量与逐点 `CURRENT STRUCTURE` 建表，选点切换实际结构；TS 没有逐点结构时明确留空。来源读取在 worker 中执行，64 MiB 上限，完整文件 SHA-256 与导入时不同则拒绝展示。结构页面提供可拖动旋转球棍预览、坐标表及 CSV；振动仅计算谐振频率行，忽略重复 normal-coordinate listing；热化学各字段与条件保留单位和原始行号；表格导出复用当前科学结果；日志按作业加载纯文本。

真实本地 Gaussian16 频率样本核对为 54 个谐振模式（非重复计数）、首项 53.1981 cm⁻¹/第 777 行、0 个虚频，Gibbs 校正 0.143352 Eh/第 2057 行、Gibbs 总量 -382.164915 Eh/第 2061 行。Gaussian16 NBO 3.1 回归输出核对了 NPA/E(2) 表格格式。真实 Qt/controller 验证通过；RF8 parser 专项 6 passed；全量 312 passed，最终本地化后的 RF8/workbench 焦点回归 32 passed。详细范围和阻塞见 [RF8 验收记录](rf8-validation.md)。

公开 Gaussian16 `HCN-ts-irc.log` 实际核对 10 个正向点、10 个反向点、TS 汇总行及 20 个三原子逐点结构；完整样本只保存在本机临时目录，不纳入仓库。点和汇总反应坐标交叉核验，失配拒绝展示；单方向不会被补成双方向。RF8 专项 11 passed、全量 317 passed（含真实输出、Qt 选点与来源 SHA 失配），详细来源、限制与测试命令见 [RF8 验收记录](rf8-validation.md)。NBO 范围仍为 Gaussian NBO 3.1；其他 IRC 布局需实际样本扩展。后续用户要求发布 `v.1.0`，Windows 包已构建并完成二进制/资源/ZIP 审计；实际 WebEngine 页面烟测在当前主机上失败，源码、冻结版及原 0.2.0 包表现相同，详见 [v.1.0 包验收记录](v1-validation.md)。

## 2026-10-17：RF7 完成，GaussianReaderPro 0.2.0 本地 Windows 包已复验

产品显示名、版本、Qt/导出标识与 Windows PE 信息统一为 **GaussianReaderPro 0.2.0**；保留内部包名及旧设置/恢复目录。新包包含 RF1–RF6 与用户追加多路径功能。真实 EXE 验收发现并修复冻结 SVG/PDF 后端遗漏；补齐语言键、长保存路径页脚、1100 工具条横向滚动与立方体位置、tooltip 轴文字避让。

最终全量 **306 passed**（1 项非功能性 pytest cache 权限警告）；源码/新 EXE 主链各 **27/27**，独立重启与窗口/DPR 矩阵 **43/43**，搬移后的 EXE 离线导出页及 DOM 布局 **11/11**，包审计 **9/9**。最终 EXE 实际拖动 **52.89 FPS**，选择/详情 p95 **33.5/75.7 ms**。源码与包内 **36 个资源** SHA 一致，PNG/SVG/PDF、CLI/WebEngine 烟测通过。中间详情 p95 205.1 ms 的未通过运行保留；最终诊断器用释放 GIL 的 Qt 原生事件循环等待。

证据：[RF7 验收记录](rf7-validation.md)、[综合原始报告](../artifacts/rf7/validation.json)、[Windows 便携包](../artifacts/releases/GaussianReaderPro-0.2.0-Windows-x64-portable.zip)、[兼容启动器](../dist/GaussianReaderPro/Launch-GaussianReaderPro-compat.cmd)。EXE SHA256：`4889b26df64fa8b1db4c1d6755b3ddab59fb8a97b102abfef5994e168ad8478d`。默认相机、截图分区、对比度、内存与全部绝对路径见报告。

本机仍使用亲和性 `0xffffff3f`；默认调度、GPU 显存、macOS/Linux 未验证。仅完成能量页 RF7，不将其他导航模块标为完成；RF8、S8/S9 未启动，未发布远端 Release。以下保留历史事实。

## 2026-10-17：用户追加多反应路径与自定义颜色

能量页新增“+”创建路径，支持颜色选择/十六进制输入、显式已有节点与排序，以及空路径后续编辑；继承当前能量类型/单位/参考并开启比较。完整路径列表提供显隐、切换活动路径、独立改色。多条路径共用现有高光与面积阴影算法，增加深度时重新适配构图；概览图例不截断，能量表支持横向滚动。所有科学比较与参考检查保留。

当前源码实际创建 C/D/E 后，五路径/20 节点验收 **22/22**，相关回归 **48 passed**。含真实 Qt 创建/选色、非活动路径改色、二维/三维五路径、保存、新进程恢复及离线比较；JS 错误/远程请求 0。仅末尾截图一次。证据与使用方法见 [多路径验收记录](multi-path-validation.md)、[原生报告](../artifacts/multi-paths/validation.json)、[五路径实际截图](../artifacts/multi-paths/run-cd9ccdb637/five-paths.png)。这是 RF6 后的用户功能追加；RF7/RF8、S8/S9 未启动，EXE 未重建。

## 2026-10-17：RF6 完成，独立重启与新 renderer 离线导出通过

项目视图保存选中 ID、详情/抽屉与独立二维范围/三维相机，旧 Plotly 相机仍可显式转换；只读项目视图修改留在临时状态。3D PNG 直接捕获当前 Three，菜单区分仅图表与实际 WebEngine 工作台展示图。离线 HTML 携新 Three 场景、分子坐标、资源与许可，移动目录后从 file:// 运行，无 Qt bridge/远程依赖。只嵌入已核验的选中结构，其他节点明确无嵌入坐标；审计表和来源复核覆盖离线可切换显示的路径，SQLite v1 与科学数值不变。

最终 Windows 真实 Qt/WebEngine **31/31**，两个独立进程 PID 2492、42468；覆盖磁盘保存、新进程恢复、旧相机迁移、Three PNG、工作台 PNG、移动后的离线页/分子、Compare 往返、WebGL 降级、导出冲突与捕获超时恢复。远程请求/JS 错误 0；相关回归 **45 passed**。集中验证中发现并修复了离线 Compare 初始状态遗漏与重新开启问题，失败记录保留。

证据：[RF6 验收记录](rf6-validation.md)、[最终报告](../artifacts/rf6/validation.json)、[工作台展示 PNG](../artifacts/rf6/run-b4f4796126/workbench/profile.png)、[离线 HTML](../artifacts/rf6/run-b4f4796126/offline-3d/profile.html)。分享 HTML 时须复制整个文件夹。当前仅完成源码；Windows EXE 未重建，RF7/RF8、S8/S9 尚未开始。

## 2026-10-17：RF5 完成，二维/三维交互与窄窗适配已验证

二维图补齐平移、框选缩放、键盘缩放与适配；三维图支持旋转、缩放与适配。真实有效节点可用方向键/Home/End 浏览、Enter/Space 选择；选择按 UUID 在模式切换后保留。路径显隐同步比较状态，隐藏当前路径会清除该路径选择；无兼容可见路径时比较禁用。窄窗详情抽屉可打开并由 Escape 关闭。多路径重叠节点标签分置两侧，不修改科学数值。

真实 Windows Qt/WebEngine 验收在 DPR=1、1.5 各 **19/19**，无 JS 错误；相关源码回归 **40 passed**。实际 Qt 截图和报告见 [RF5 验收记录](rf5-validation.md)、[DPR 1 报告](../artifacts/rf5/validation-dpr1.json)、[DPR 1.5 报告](../artifacts/rf5/validation-dpr1_5.json)。当前完成范围为源码；未重建 Windows EXE，未验证其他平台。RF6 完整离线导出与 renderer 迁移尚未开始，RF7/RF8 亦未开始。

## 2026-10-17：RF4 完成，来源结构与右栏联动已验证

新增独立、限作业边界的结构读取服务，复用现有串行 worker，读取时复核来源 SHA；Standard/Input 优先规则、单位、行号、取消/大小限制与过期请求守卫均落地。同一个 WebEngine 内增加可旋转的球棍预览，完整详情/显式前驱势垒、全部来源及日志行定位、SVG 双路径概览、关键能量表均接通。多来源表达式须显式选择分子；步骤表仅按显式 ID 配对，不按同名/数组位置猜测。

最终源码真实 Qt/WebEngine **22/22** 通过（PID 43864），1672×941/DPR=1；75 项相关回归与 12 项表达式编辑/保存回归通过。100 次分子更新为 10 objects / 2 geometries，隐藏/闲置无持续 RAF，JS 错误 0。修复重叠概览点选、复制动作回调时机、多来源提示状态，以及 Three 内联样式导致旧分子帧未隐藏的问题。

报告 [rf4-validation.md](rf4-validation.md)、[原始验收](../artifacts/rf4/validation.json)、[英文深色截图](../artifacts/rf4/rf4-en-dark-1672x941.png)。结构/能量夹具为明确标记的合成例；不代表所有 Gaussian 版本已兼容。按阶段表停在 RF4，RF5–RF8 未启动，EXE 未重建。

## 2026-10-17：RF3 完成，Three.js 与真实交互/重启验证通过

新增离线 Three.js r170 专用 3D 场景：正交相机、共同能量轴、屏幕尺寸光线/圆节点、橙白选中环、逐路径渐隐透明幕、HTML 标签/全部来源 tooltip，以及随相机联动且可点击的方向立方体。2D 保留 Plotly；WebGL 不可用时明确说明并切到 2D。`three_v1` 相机状态走白名单，旧 Plotly 相机显式转换，SQLite v1 不变。

集中真实源码验收 **33/33** 通过（PID 48936），独立重启新进程恢复与相机菜单 **3/3** 通过（PID 43772）；1672×941 DIP、DPR=1，默认投影占图区宽 90%、高约 78.5%，8 标签无重叠，真实鼠标选点/旋转/平移/方向轴、前后透明层、缺值断线及降级通过。100 次更新资源计数稳定，闲置/隐藏无持续 RAF，JS 错误 0。修复冻结数组 tuple/list 比较引起的反复备份与事件过期；相关源码回归 71 passed，最终相机菜单专项 3 passed。

完整记录 [rf3-validation.md](rf3-validation.md)，原始 [主验收](../artifacts/rf3/validation.json)、[独立进程恢复](../artifacts/rf3/restore-validation.json)，[默认截图](../artifacts/rf3/rf3-en-dark-1672x941.png)。本轮按用户要求停在 RF3；RF4 右栏实际数据仍占位，RF6 导出迁移及 RF7 EXE 未开始。

## 2026-10-17：RF2 完成，固定画布与真实截图已通过

RF2 源码验收完成。修复隐藏控件的父组件归属；Qt 顶栏/侧栏与单个 WebEngine 能量页按参考图拆分，使用专用 tokens 和 CSS Grid。能量页的旧 Qt 多层页签/参数行/详情栏及 Plotly modebar 已去除，节点编辑保留在菜单内；后续分析模块各有独立、明确标注的占位路由。

上轮关于“桌面仅 1442×951，因此无法验收”的判断有误，该数字是窗口截图尺寸。新的验收程序直接启动带 PID 标识的当前源码，实际创建 1672×941 DIP、DPR=1 内容区。顶栏、侧栏、主图列、右栏及顶部/底部工具栏宏观边界误差均为 0 DIP；WebEngine 维度/路径/比较按钮通过，标准画布右栏无滚动，JS 错误为 0，相关源码回归 **69 passed**。

变更/命令见 [rf2-validation.md](rf2-validation.md)，原始报告 [validation.json](../artifacts/rf2/validation.json)，真实截图：[EN/dark 1672×941](../artifacts/rf2/rf2-en-dark-1672x941.png)、[CN/light 1440×900](../artifacts/rf2/rf2-cn-light-1440x900.png)。当前仍为实际运行的 Plotly scatter3d 4.1.1；分子/概览/表格/方向立方体为后续阶段占位，RF2 未重新打包。按阶段表在 RF2 停止。

## 2026-10-16：RF0 基线、演示数据、资源检查

RF0 已完成。新增独立双路径合成夹具（8 个独立节点 UUID），并实际运行源码版和现有 Windows onedir 包；两者都显示了 3D 双路径图。夹具的显示值通过真实项目计算链核对：Path A `0, +15.060, -5.020, -15.688`；Path B `0, +11.420, -2.800, -12.400 kcal/mol`。项目使用 CODATA 2022 热化学卡常数 `627.5094740628974 kcal/mol/Eh`。

证据文件：

- [合成夹具说明](../tests/fixtures/profile_replica/README.md) 与生成器 `tools/build_profile_replica_fixture.py`。
- [基线报告](../artifacts/rf0/baseline.json)：运行环境、项目节点/数值、源码/包哈希、字体/DPR、WebEngine 能力、渲染资源清单和截图哈希。
- [源码实际窗口截图](../artifacts/rf0/source-baseline.jpg)；[Windows 包实际窗口截图](../artifacts/rf0/exe-baseline.jpg)。两张均为 Windows.Graphics.Capture 获取的 1442×951 实际窗口图，深色主题，3D 双路径比较打开。
- `tools/check_profile_replica.py` 完成夹具值、资源清单、截图以及源码/包 WebEngine 运行信息核对，退出码 0。打包程序 smoke 报告通过；运行时 Plotly 版本为 4.1.1。清单记录 Python Plotly 包版本为 7.1.0，二者是不同版本字段，不应混淆。

已知基线限制：当前正式运行图仍使用 Plotly.js `scatter3d`，不是 RF3 目标 Three.js；包中未包含 Three.js。桌面当前 DPR 为 1.25，窗口截图分辨率不是 RF7 规定的 1672×941 验收画布。合成日志仅用于视觉与资源基线，不代表真实 Gaussian 输出兼容性。此阶段只记录现状，没有开始 RF2 视觉改版。

## 2026-10-16：RF1 显式表达式保存与重启恢复

RF1 已实现。表达式编辑器现在有“保存表达式”“保存并关闭”“关闭”三个明确入口，并显示目标项目路径/恢复副本状态。保存会先提交编辑器草稿和构建器状态，等待当前串行任务完成，再为未命名/只读项目弹出 `.grproj` 另存对话框；收到项目保存状态后才报告成功，失败会保留编辑器内容并提供重试/另存为。编辑器内绑定标准保存快捷键。

真实 Qt 验证：`tests/test_node_editor.py::test_explicit_expression_save_survives_fresh_controller_restart` 使用实际 `ExpressionDialog` 和 Qt 鼠标点击，输入表达式并点击保存，验证 `.grproj` 写入及成功状态显示目标路径，然后创建全新 `ProjectController` 从该文件打开并核对表达式文档完全一致。单项命令结果 `1 passed`；完整 `tests/test_node_editor.py` 结果 `12 passed in 31.09s`。这是新控制器/新恢复目录的会话重启验证，不是关闭并重新启动桌面进程的截图验收。

| 阶段 | 状态 | 证据/下一步 |
| --- | --- | --- |
| RF0 基线/合成数据/资源锁定 | 完成 | 合成双路径、源码与 Windows 包实际窗口、资源/运行版本哈希及 WebEngine 能力见上文和 `artifacts/rf0/baseline.json` |
| RF1 表达式明确保存 | 完成（源码 Qt 会话验证） | 显式保存、保存并关闭、失败保留与另存入口；重启恢复测试通过；尚未做独立桌面进程截图验收 |
| RF2 专用布局/主题 | 完成（源码） | 1672×941/DPR=1 真实 Qt/WebEngine，宏观边界误差 0 DIP，69 项回归；见 `docs/rf2-validation.md` |
| RF3 新 3D 渲染与交互 | 完成（源码） | Three.js r170、33 项真实场景检查、独立进程恢复 3 项；见 `docs/rf3-validation.md` |
| RF4 详情/分子/双路径概览 | 完成（源码） | SHA/作业边界核查、真实结构读取、显式步骤配对、22 项原生检查及 75+12 项回归；见 `docs/rf4-validation.md` |
| RF5 2D/完整交互/适配 | 完成（源码） | DPR 1/1.5 原生 Qt/WebEngine 各 19 项、40 项相关回归；见 `docs/rf5-validation.md` |
| RF6 保存状态/离线导出 | 完成（源码） | 31 项真实 Qt/独立重启/离线检查、45 项相关回归；见 `docs/rf6-validation.md` |
| RF7 视觉/性能/Windows 包复验 | 完成 | GaussianReaderPro 0.2.0；306 回归、97 原生检查、11 离线检查、9 包审计，见 rf7-validation.md |
| RF8 其他导航模块真实功能 | 未开始 | 逐模块独立解析与实际样本验证 |

RF1 本阶段修改：`ui/expression_editor.py`（按钮、状态、排队保存、错误/取消路径）、中英文 locale、新增 Qt 重启回归测试。无表达式编辑器专属桌面截图；无打包或发布。RF0 实际窗口截图只记录复刻前 renderer 基线，不作为 RF1 编辑器验收证据。

## 历史：RF2 初次尝试（当时进行中，尚未验收）

已落地的代码范围：

- `ui/main_window.py`：主窗口内容边界采用无外层间距的 50px 顶栏和 196px 侧栏；能量图视图隐藏重复页标题、参数行、节点编辑行及旧横向页签，主图与右侧详情按约 1060:387 分栏。节点/编辑仍可从工具条“更多”进入。
- `presentation/palette.py` 与 `resources/themes/lavender_sunset.json`：新增独立 light/dark profile tokens；dark 值按 RF 指导书冻结为近黑紫背景、细边框、紫/橙路径和橙色焦点，不改其他页面原有基础颜色。
- `ui/glass_widgets.py`、`ui/theme.py`：能量页专属外框和面板材质样式；减弱该页背景辉光，保留普通页面现有绘制行为。
- `ui/profile_view.py`：主工具条收成单行，保留 2D/3D、路径显隐、比较、重置、导出；主题、相机、编辑/详情切换收进“更多”菜单。图表基色开始读取独立 profile tokens。
- `resources/locales/en_US.json` 与 `tests/test_plot_spec_export.py`：补英文菜单文案及新焦点颜色的回归断言。

验证：`python -m compileall -q src/gaussianreadpro` 成功；`python -m pytest tests/test_glass_preferences.py tests/test_plot_spec_export.py -q` 为 `37 passed`。桌面实际窗口截图/1672×941 几何量测尚未通过：当前桌面为 1442×951、DPR 1.25，未能取得 1672 DIP 画布；GUI 检查到的窗口仍是 RF0 旧界面，因此不将它记录为新布局证据。没有触碰 Three.js/3D 重构（RF3）或分子和详情数据实现（RF4）。RF2 尚未达到阶段门槛，状态保持进行中。

## 历史：2026-10-16 指导书交付，代码实现未开始

用户反馈当前程序与指定 3D 参考图差异明显，表达式构建缺少明确保存选项。新规范见 [ENERGY_PROFILE_REPLICA_GUIDE.zh-CN.md](ENERGY_PROFILE_REPLICA_GUIDE.zh-CN.md)。本记录不覆盖 EP1–EP6 的历史功能验收，但历史验收不能证明本轮视觉目标已达成。

已完成的文档工作：

- 保存本次用户原始参考图到 `docs/design/energy-profile-replica-target.png`；SHA-256 为 `6F1C8818C046DF6FDAF6A63DBB4ABA5CC07B095CBC431F96B66C728FF8413D01`。
- 复制历史 EP6 实际截图为 `docs/design/energy-profile-replica-baseline.png`，并实际查看。它是历史截图，本轮未重新运行应用或生成新 Qt 截图。
- 核查主窗口、profile 页面/JS、详情组件、表达式编辑器、controller/session、数据模型和主题资源。
- 确认表达式当前依赖 350ms 自动提交及主窗口项目保存，弹窗只有“完成”，没有显式保存按钮和磁盘成功状态。
- 确认当前 JobRecord 无直接可用的结构坐标字段；分子预览、参考图其他分析导航不能声称已经实现。
- 制定布局尺寸、tokens、渲染架构、3D 图层、科学一致性、保存状态机、逐阶段交付和截图验收要求。

| 阶段 | 状态 | 证据/下一步 |
| --- | --- | --- |
| RF0 基线/合成数据/资源锁定 | 未开始 | 先运行当前源码与当前包，记录真正运行版本/renderer/截图 |
| RF1 表达式明确保存 | 未开始 | 可优先独立实施，详见指导书第 9 节 |
| RF2 专用布局/主题 | 未开始 | 固定 1672×941 内容区验收 |
| RF3 新 3D 渲染与交互 | 未开始 | Three.js 离线资源、透明层、相机与选择 |
| RF4 详情/分子/双路径概览 | 未开始 | 结构读取不得跨作业或绕过来源校验 |
| RF5 2D/完整交互/适配 | 未开始 | 可见按钮都有行为，CN/EN 与高 DPI |
| RF6 保存状态/离线导出 | 未开始 | 新 renderer 与旧项目/审计包兼容 |
| RF7 视觉/性能/Windows 包复验 | 完成 | GaussianReaderPro 0.2.0；306 回归、97 原生检查、11 离线检查、9 包审计，见 rf7-validation.md |
| RF8 其他导航模块真实功能 | 未开始 | 逐模块独立解析与实际样本验证 |

本次仅修改指导与交接文档、复制参考/历史基线图片；未修改应用代码、未修复保存功能、未重新打包、未上传或发布 GitHub Release，也未启动 S8/S9。

后续记录模板：日期 / 阶段 / 代码范围 / 用户可见变化 / 测试命令与结果 / 实际 Qt 截图 / 视觉差异 / 保存与来源验证 / 阻塞项 / 下一阶段。截图基准、渲染参数、字体和包版本必须一起记录。
