# 能量剖面图 V2：二维清晰度与三维交互实施方案

状态：EP1–EP6 已实施并验收；最终报告见 `docs/ep6-validation.md`。2026-10-15 用户明确要求还原 demo 的平滑高光曲线、圆形点、橙色选中光晕和 3D 面积虚影；D038 覆盖早期“水平能级 + 虚线”的展示取舍。基线为 S7 + 液态玻璃 G6；原总方案的 S8 与本专项分开跟踪。阶段结果和限制见 `docs/energy-profile-v2-progress.md`。

参考图：[二维示意](design/energy-profile-liquid-glass-demo.png)、[三维示意](design/energy-profile-liquid-glass-3d-demo.png)。按用户修正，使用经过真实节点且不超出相邻端点值域的平滑展示曲线、多层高光、圆形节点与橙色选中光晕，三维增加半透明光带和投影幕。曲线/光带仅作视觉引导，数值和能垒只取真实节点，缺值断开。详见 D038。

## 1. 用户可感知的最终行为

1. 默认二维/三维主图占据路径页完整高度，节点表单独页签。曲线、圆形节点、参考零线、单位、名称与缺值断点清楚可读；选中节点有落日橙光晕和清晰悬浮卡。路径颜色保留用户设置。
2. 三维的 X 是反应步骤，Y 是路径类别，Z 是相对或绝对能量，Y 不是假造的连续反应坐标。多路径沿 Y 分层，用户能用旋转、平移、缩放、正视/俯视/等轴测预设比较。悬浮和右侧详情精确给出数值，透视画面不承担读数的唯一职责。
3. 顶部 2D/3D、比较、路径显隐、复位、导出可见且可键盘操作。选中节点后，工作台现有右侧属性区显示一张只读图表摘要，含当前路径数值、单位、绝对/参考能量及来源。放大窗口提供相同摘要的可折叠侧栏；窄窗隐藏侧栏，仍可用悬浮卡和原节点页查看。
4. 相机、图表视口、路径显隐和模式按现有项目视图状态恢复；语言与主题即时切换。HTML 结果包离线可用；二维纸张导出保持高对比白底，三维 PNG 能读到轴、单位和节点标记。

### 与视觉稿的取舍

- 保留图中的视觉层次、薰衣草紫/落日橙、悬浮卡、右侧详情、路径分层、工具条和小型二维概览。
- 保留平滑发光曲线和三维光带外观；不照搬虚构的文件、能量、频率或分子坐标。来源来自 `dependencies` / `reference_dependencies`。曲线采样只在展示字段 `curve_runs` 中，科学值仍为真实 `points`。
- 三维右侧缩略图可由同一 `plot_payload` 绘制为**只读小型二维概览**，不创建第二个 WebEngine。若首版会显著挤占画面，先交付准确的文本详情与路径色图例，再在 EP4 加缩略图。

## 2. 当前代码入口与不能改变的契约

| 任务 | 当前入口 | 要保留的约束 |
| --- | --- | --- |
| 科学值及显示数据 | `src/gaussianreadpro/core/plot_spec.py`：`build_plot_spec`、`plot_payload`、`compare_points`、`clean_view_state` | Python 唯一计算源，内部 Hartree；无效点 `None`，不能补 0；参考只能减一次；TS 势垒须用户显式选择相邻前驱后标记 |
| Qt 容器、桥接和状态 | `src/gaussianreadpro/ui/profile_view.py`：`ProfilePanel`、`PlotBridge` | 保持协议 2；事件校验 `project_id/revision/render_id`；只读项目只在会话内保存视图；不新建 WebEngine 实例来放大 |
| 绘图 | `src/gaussianreadpro/resources/plot/profile.html`、`profile.js` | 继续用随包 Plotly.js、离线 CSP、`Plotly.react` 串行队列、一次性监听器；文本全部转义，不能直接注入 `innerHTML` |
| 工作台详情 | `src/gaussianreadpro/ui/main_window.py` 的 `self.inspector`、`update_inspector` | 保留现有标签/角色/表达式编辑与来源证据；图表摘要只读，不重复业务计算 |
| 主题和语言 | `presentation/palette.py`、`resources/themes/lavender_sunset.json`、`ui/i18n.py`、两份 locale JSON | 使用现有 dark/light tokens，不添加另一套硬编码品牌色；新文案 CN/EN 成对出现 |
| 导出 | `services/plot_export.py`、`static_plot_worker.py` | `plot.json`、CSV、来源审计、manifest 和原子发布语义不变；3D PNG/HTML，2D PNG/SVG/PDF/HTML |
| 验证 | `tests/test_plot_spec_export.py`、`tests/test_workbench.py`、`tools/check_s7.py`、`tools/check_glass_g5.py` | 不将 offscreen 测试冒充真实 WebEngine/WebGL 验收 |

契约详见 `docs/contracts.md` v1.8、`docs/decisions.md` D033–D038 和 `docs/handoff.md`。现有三维 trace 已是 `scatter3d`，对应 `x=step, y=path.category, z=value`；不要把 Z 误改成路径类别。多路径比较仍遵守 `plot_payload` 的能量类型/模式筛选以及参考签名警告；不同零点不能显示跨路径数值差。

## 3. 视觉和交互细则

### 3.1 图表材质与层级

- 通过 `_visual_style()` 将已有 `surface/elevated/text/muted/border_soft/lavender/sunset` 等 token 作为可序列化显示字段发送到页面；绘图区域使用近乎实色背景，外层卡片体现玻璃材质。网格线细而弱，零线比普通网格更醒目。禁用持续闪烁或粒子动画。
- 正常点保持路径本色；仅当前选中点外圈、TS 激活提示和主动操作使用 `sunset`。同一画面最多一个强橙色焦点。悬浮卡采用 `elevated` 背景、高对比文字和轻边框，不遮挡图轴。
- 图轴总是显示真实能量类型与单位：相对 Gibbs 为 `ΔG / kcal/mol`，电子能为 `ΔE`，绝对模式不得写 `Δ`；较窄宽度使用现有动态简称，tooltip/辅助名称保留完整语义。
- 字号以现有 12–13px token 为下限；图例和标签密集时减少常显标签，保留 hover 和右侧详情。40 点以上现有标签策略继续有效。

### 3.2 二维主图

- 真实节点为带柔和光晕的圆点，选中后橙色双圈高亮；曲线采用多层透明高光，不画能级横杠。相邻有效节点间使用 smoothstep 展示几何，不超出端点值域；无效节点断开。说明为“曲线与光带仅作视觉引导，数值以节点为准”。
- Hover 卡第一屏仅显示路径、节点、当前数值、单位、绝对/参考能量和来源名/作业；详细行号、SHA、表达式放到右侧详情或展开区，避免 hover 巨大遮挡。缺值与直接差值模式显示适当的 `—`，不要捏造绝对能量。
- 当前选中点的细投影线、零线和可选势垒括号要准确锚定节点。势垒只在现有 `barrier` 状态有效时出现；文案按 `kind` 显示 `ΔG‡`、`ΔE‡` 或热校正相应记号，不默认生成。

### 3.3 三维主图

- 使用 `scatter3d` 渲染多层发光曲线与真实圆形节点，每条路径独立 Y 类别轨道。`mesh3d` 光带与低透明度投影幕只装饰单一路径，不跨路径生成势能面。保留弱零平面与节点投影，选中投影为橙色。全部装饰 trace 必须 `hoverinfo:'skip'`，不能抢占选点或图例。
- Y 轴 ticktext 优先路径显示名，长名截断并在图例/详情保留全称；Z 轴为能量及单位。相机初始位置确保多路径不重叠，提供等轴测、沿 Y 正视、俯视三个预设和“恢复保存的相机”。预设改变只属于视图状态，不改变结果。
- 控件采用现有 Plotly orbit/pan/scroll zoom，并用 Qt 可见按钮切换。小方向指示器只有在能随实际相机正确更新时才实现；否则用三轴标签与相机预设，不做误导性的静态立方体。
- 单路径仍可进入 3D，但显示说明“深度轴为路径类别；比较两条路径时更有用”。WebGL 无法使用时沿用现有二维回退并显示原因。

### 3.4 状态、详情和可访问性

- 顶部路径开关使用 `hidden_paths` 白名单；1–4 条路径可显示切换按钮，更多路径折叠到菜单。比较开关仍使用现有 `compare`，隐藏路径与取消比较不能改变项目科学数据。
- 节点身份始终按 `path_id + entry_id`，来源仍按 UUID/作业/行号；同名节点不能串选。表格选中 ↔ 图表选中 ↔ 详情更新双向联动，保留 Ctrl/Shift 双点比较。
- 增加“选中节点只读摘要”，由 `plot_payload` 的当前点和 dependencies 填充；字段 `value`, `absolute_hartree`, `reference_hartree` 依模式显示。现有可编辑 inspector 保持独立区块。展开图表只读侧栏使用相同 view-model，避免两处拼字符串出错。
- 窄窗 `<1024` 沿用 G6 的“路径节点 / 能量图”整高页签；图表 `<900` 使用短 toolbar 文案；右侧详情收为弹出/折叠，不压缩图到不可读。键盘 Tab 顺序、焦点框、AccessibleName/tooltip 要真实可用。减少动效偏好需影响新增 hover/选择过渡。
- 新视觉控制只存到现有 `plot_state` 白名单；若增加 `camera_preset` 或 `inspector_open`，先扩展 `clean_view_state` 严格白名单及存储回归。能用现有 `viewports`、`hidden_paths`、`mode`、`compare` 完成的，不扩 schema。

## 4. 分阶段实施：每次只交给一个低成本模型任务

每阶段只让模型读取本阶段列出的文件及必要依赖，完成后提交代码、测试结果、真实截图和简短交接，再开下一阶段。官方 OpenAI Docs 的模型选择指南将 Luna 用于范围明确、成本敏感的任务；项目建议 EP1–EP5 使用当前可用的 **gpt-6-luna / medium**，EP3 的 WebGL 交互或跨文件状态问题可先尝试 Luna / high，连续两次修复失败再升级 **gpt-6.1-sol / medium**。EP6 复核若发现科学契约或架构冲突，也升级 Sol；无需一开始就让高成本模型通读整个仓库。模型建议为本项目推断，非官方对本项目的保证。[OpenAI Docs: Model selection](https://developers.openai.com/api/docs/guides/model-selection)

| 阶段 | 交付 | 主要文件 | 最小验收 |
| --- | --- | --- | --- |
| EP1 容器和主题 | 图表工具栏、路径显隐入口、宽窄布局及背景层；不改 trace 形状 | `ui/profile_view.py`、`ui/theme.py`、locale JSON、必要的 `main_window.py` | 1440×1000、1100×820、860×680 真实 Qt 截图；CN/EN、浅/深、键盘入口；旧图行为不变 |
| EP2 二维读图 | 平滑高光曲线、圆形选中点、零线、hover 信息分层、势垒文案；Python 生成显示所需字段（D038 更新） | `profile.js`、`profile.html`、`ui/profile_view.py`、必要时 `core/plot_spec.py` 的**显示字段** | 四点样例数值与现有 oracle 一致；无效点断线；参考/模式/单位切换正确；HTML 转义回归 |
| EP3 三维交互 | 分层路径、投影线、弱零平面、相机预设、orbit/pan、Y 路径名、WebGL 回退 | `profile.js`、`profile.html`、`ui/profile_view.py` | 真 Qt/WebGL 旋转与选点、相机保存重开、两路径不同参考警告、1/2/多路径及 3D PNG；trace/监听器不随更新累积 |
| EP4 详情与小概览 | 图表选中点的只读摘要、来源证据、右侧 2D 小概览，展开/窄屏适配 | 新 `ui/plot_inspector.py`、`ui/main_window.py`、`ui/profile_view.py` | 同名节点不串选；未计算/无效/直接差值不显示伪值；展开和紧凑截图；详细来源可以定位到文件/作业/行号 |
| EP5 状态与离线导出 | 全部控件与既有 `plot_state` 一致；独立 HTML 和截图样式可读 | `core/plot_spec.py`（仅视图白名单）、`profile.js`、`services/plot_export.py`、相关测试 | 保存/重开视图；只读项目探索不写库；2D 四种格式和 3D PNG/HTML；来源变化拒绝导出；不覆盖目标目录 |
| EP6 综合验收与交接 | 全量测试、真实 Qt/WebGL 截图矩阵、性能和文档 | `tools/check_s7.py` 或新专项脚本、`docs/energy-profile-v2-progress.md`、`AI_HANDOFF.md` | 完整检查记录通过/失败条件；不把受限环境的页面加载失败当成产品回归；不宣称未经测试的平台已通过 |

EP2/EP3 若需要 Plotly 新 trace，限定在渲染层；不要扩大 `PlotSpec` 的科学值语义。EP4 只读摘要可抽取纯函数，给没有 Qt 的测试直接使用。

## 5. 可直接复制给后续模型的逐阶段提示词

专项已完成。后续维护可复制提示词：

> 先读 `AI_HANDOFF.md`、`docs/ep6-validation.md`、进度记录及 D038，保持平滑高光曲线、圆形节点、选中光环和 3D 装饰光带；仅修改用户此次明确指定的问题，保持科学节点、来源验证、协议 2 和保存恢复边界。按影响范围回归并更新实际截图与交接。不自动启动 S8/S9，不宣称未测平台或发行包通过。

后续每轮将 `EP1` 替换为 `EP2` … `EP6`，并在开头加一句“先读上阶段进度记录，保持已验收交互”。每阶段的最终回复必须说清：修改文件、用户可见变化、测试命令及结果、真实截图路径、仍未完成的下一阶段。若某阶段被 WebEngine/本机原生崩溃阻塞，应保留失败证据、继续完成能独立验证的部分，不能伪称真实 3D 已通过。

## 6. 验收清单和环境边界

- 科学：四点 oracle `0, +15.0602273775, −5.0200757925, −15.6877368516 kcal/mol` 保持；不同 `kind/mode/reference_signature` 不错误比较；缺值、草稿、来源变更不出旧值；势垒只有明确选择后显示。
- 交互：同名节点、路径显隐、双点选择、2D/3D 切换、鼠标滚轮、orbit/pan、相机预设、重置、展开、语言主题切换、只读项目、重开恢复；JS 监听器仅绑定一次。
- 画面：深浅主题、CN/EN、宽/窄窗与 DPR 1.0/1.5/2.0；文字、单位、零线和来源可读；对比模式不出现两条路径误叠或错误跨参考差。
- 导出：2D PNG/SVG/PDF/HTML、3D PNG/HTML 的真实文件打开核查；`plot.json`/`sources.csv`/manifest 校验继续通过；HTML 完全离线；3D PNG 不承诺矢量。
- 性能：基于现有 G6 的 100 次更新记录时间、render count、trace 数、监听器数以及 WebEngine 子进程内存；新增轨道/投影线后至少不能随更新线性累积。明确测量环境，不将一次样本当跨平台结论。
- 本机约束：G4 默认调度崩溃未关闭。用户已要求暂置硬件/运行时排查；Windows 验收若使用 `run_app_compat_windows.cmd` 或亲和性 `0xffffff3f`，必须在报告里注明。macOS/Linux 和正式安装包仍待后续平台实测，不能因 Windows 源码截图通过而宣布跨平台完成。

阶段进度记录只追加确认事实：完成项、失败项、命令、截图、测试范围、限制、下阶段入口。任何阶段若科学或渲染协议必须变化，先在 `docs/decisions.md` 补新决策，再更新计划和测试；不要在 JS 中偷偷加入能量计算。
