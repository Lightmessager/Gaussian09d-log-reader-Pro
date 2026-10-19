# GaussianReaderPro 可视化工作流与入口修复项目书 v2.0

日期：2026-10-18  
执行对象：Luna；每个 U 阶段独立实施、复核和报告。  
工作目录：D:\Project\GaussianReadPro  
状态（2026-10-18）：U0 基线已完成并做只读复核；U1–U7 源码阶段及 U7 本机用户路线/兼容性验收已完成；用户另行启动的 U8 已全量构建 Windows x64 2.0.0 便携包并完成包审计和 EXE 默认界面验收。U8 的 WebEngine 页面烟测在源码与冻结版均失败，Agg PNG/SVG/PDF 与从默认首页新建、改名、打开搭建器均通过。详见 `docs/ux-v2-validation.zh-CN.md` 和 `docs/ux-v2-u8-validation.zh-CN.md`。U5 曾记录的单进程 Qt 原生中止在 U6 回归中未复现。

执行方式：Luna 在当前会话按检查框逐任务实施；若执行环境安装了 superpowers，使用 superpowers:executing-plans。没有该插件也能按本文接口、步骤和验收独立实施，不需要启动子代理。  
架构：现有 PySide6/Qt 原生壳层与搭建窗口，共用 ProjectController、串行 SessionBackend 和 Python 科学核心；可视画布只组织编辑意图。  
技术：Python 3.12、项目锁定的 PySide6、QGraphicsView、SQLite v1、既有本地 Plotly/Three 与协议 2。依赖版本沿用 requirements-s7-windows-lock.txt。  
规格依据：本文第 1–8 节；实施计划为第 9 节；全局约束与审查重点为第 12 节。

## 1. 用户目标与本次交付范围

用户打开程序后，应看得见反应路径编辑器和项目重命名，并能理解下一步该做什么。常见路径从“创建项目 → 导入日志 → 选择作业 → 搭建阶段 → 设置零点 → 检查并保存 → 查看图表/导出”在一个连贯流程内完成。阶段、物质、反应边、能量表达式、来源证据和保存状态用界面直接表达，减少记忆菜单位置、反复切页和输入内部编号。

本项目修复入口与交互，并把已有科学能力组织为可用流程。继续使用现有解析、表达式 AST、路径计算、来源校验、SQLite v1、PlotSpec、导出和串行 SessionBackend。旧项目可打开，复杂表达式可保留，缺值仍明确缺值。

项目书初始编写阶段只修改文档、不重打包；实施工作随后按 U0–U7 独立推进，U8 由用户另行启动。旧项目书的 L1/L2、L4 科学规则和边界继续生效。本文取代旧项目书中关于入口、操作布局、流程引导及交付方法的描述；科学规则冲突时不得自行放宽，按第 12 节处理。

### 1.1 实施前必读

1. AI_HANDOFF.md、docs/handoff.md：识别当前状态与历史记录。
2. 本文全文。
3. docs/LUNA_UI_FIX_PROJECT_BRIEF.zh-CN.md：重点读 L3、L4.0–L4.6。
4. docs/l3-validation.zh-CN.md、docs/l4-validation.zh-CN.md、docs/l5-validation.zh-CN.md：区分实现、自动化覆盖与未完成桌面验收。
5. docs/contracts.md 与 core/reaction_network.py：不得在 UI 层另造科学语义。
6. 每阶段涉及的源码和测试；下面的行号只用于定位，实施时重新搜索函数。

### 1.2 方案选择

| 方案 | 优点 | 代价与结论 |
|---|---|---|
| A：只恢复被隐藏的按钮 | 改动小，可立即找回功能 | 长表单、旧路径空白、保存歧义仍在；作为 U1 的最小修复，不作为最终交付 |
| B：恢复入口 + Qt 可视化搭建 + 共享操作状态 | 可复用现有计算与保存链，源码及冻结版均能逐项验收 | 需要拆分搭建窗口的界面职责；推荐并作为本文执行方案 |
| C：全网页节点编辑器与新工作流后端 | 可高度定制视觉效果 | 增加桥接、持久化和两套状态同步成本；不纳入本次范围 |

## 2. 当前问题与源码证据

下表是静态源码确认的事实；U0 已补充冻结版桌面复现。冻结包早于当前 U1–U6 源码，运行结论和源码回归分别记录于 `docs/ux-v2-baseline.zh-CN.md`。

| 编号 | 用户遇到的现象/风险 | 当前代码及因果关系 |
|---|---|---|
| F01 | 主能量图找不到编辑器 | main_window.py::_reaction 创建 open_builder_button；compact_focus_changed 在 index=1 时隐藏 reaction_edit_tools，同时隐藏 compact_tabs；默认 _compact_focus_index=1。主图缺少常驻搭建入口 |
| F02 | 点击“+”没有进入完整搭建 | profile_view.py 的 new_path 事件发 pathCreateRequested，MainWindow.manage_path('new') 打开 path_editor.py::NewPathDialog；它处理路径容器与已有节点选择，不是 ReactionBuilderDialog |
| F03 | 项目名、保存和重命名不明显 | _sync_replica_shell 无条件隐藏 project_name、saved、save_button、new_button、more_button；_configure_replica_shell 将项目操作菜单放入“设置”菜单中 |
| F04 | 最近项目重命名难发现 | recent_context_menu 有改名、移除和删除，但首页列表默认只表现为可双击项；右上“最近”菜单只生成打开动作 |
| F05 | 未保存项目不能从现有改名入口改名 | rename_current_project 在没有 controller.path 时直接返回；新建名只由 _pending_project_name 临时保存，Project 模型没有独立 name 字段 |
| F06 | 新建名可能在保存失败后丢失 | save_project 调用 controller.save 后立即清空 _pending_project_name，而返回只表示任务提交，未证明写盘成功 |
| F07 | 原始来源与路径节点入口被遮蔽 | _sidebar 把“源文件”项隐藏；点击能量侧栏又把 compact_tabs 强制切回能量图。用户难以形成稳定的导航记忆 |
| F08 | 磁吸窗口仍像复杂表单 | reaction_builder.py 的 SpeciesCardList/SnapList 接收 MIME 卡片；阶段、边、能量账本、核对字段和按钮集中堆在同一长布局。它有拖入列表能力，未提供可读的阶段节点与拓扑画布 |
| F09 | 打开已有路径可能看见空阶段 | _load_recipe 只从 reaction_network_v1 的 path_reactions 查找配方；没有配方的普通导入路径由 _current_recipe 返回空阶段视图。现有 PathEntry/AST 不会自动成为可视阶段 |
| F10 | 用户不清楚应用与保存的区别 | 页脚同时提供预览、应用、保存关系网、保存文件；_save_file 遇到未应用草稿先报错，要求用户自行理解顺序 |
| F11 | 关闭窗口可能丢失未应用编辑 | closeEvent 仅断开信号再调用父类；取消按钮直接 reject，未见统一脏草稿确认或“保留草稿”落盘流程 |
| F12 | 测试通过不等于入口可发现 | 现有很多搭建测试直接实例化 ReactionBuilderDialog 或调用内部方法，没有证明用户从默认主图能点击进入 |
| F13 | 重复应用可能让选点/映射失去原身份 | core/reaction_network.py::apply_path_recipe 每次用 new_id() 生成 node/entry；不能直接假定现有接口会保留旧节点 UUID。U3 明确限定可复用身份策略，旧调用默认行为保持兼容 |

结论：先修复壳层隐藏规则与操作路由，再整理搭建交互；不能仅声称“代码里有按钮”或把“+”视为完整反应编辑器入口。

## 3. 目标界面与操作路线

### 3.1 常驻项目头栏

所有页面保留同一个项目区：项目名按钮（带下拉箭头）、保存状态、保存按钮。新建、打开和最近项目放在“项目”菜单；主题、语言、动效放“设置”。菜单分类明确。

项目名显示规则：已有具名文件取 controller.path.stem；未保存项目取项目工作区暂存名称，否则“未命名项目”。长名省略显示并保留完整名称和路径提示。窗口标题同步显示。

项目名菜单固定顺序：重命名项目…、保存、另存为…、打开所在文件夹（已保存才可用）、最近项目、关闭项目。删除放最近项目卡片的更多菜单中，并使用危险操作分组。

点击项目名后一次选“重命名项目…”即可改名；不能要求到设置页或依赖右键。项目名按钮与保存状态在 840 DIP 宽度下仍可用，品牌与页面副标题先收缩。

### 3.2 导航与路径操作栏

保持已有导航索引兼容，不直接在 QListWidget 中插入导致历史 page 数值错位的新项。恢复“源文件”的可见性，并对用户显示“计算日志”；增加稳定 route key 映射，见第 8 节。

能量页在 Qt 原生层提供常驻操作栏，不以 WebEngine 成功加载为前提：

~~~text
[路径名称 ▼] [编辑反应路径] [查看：能量图 | 节点表]    [导出 ▼]
~~~

“编辑反应路径”是有文字的主按钮，一次点击打开当前路径的搭建窗口。“+”或“新建路径”创建路径后进入搭建，不把 NewPathDialog 的节点勾选窗当作全部编辑能力。专家用户仍可从菜单选择“用已有节点建立路径…”。

不再用“再点侧栏强制回图”的隐式行为切换子视图。切换后保留选定路径、选点、相机和节点表选择；节点表必须有明显的“返回能量图”。

### 3.3 按数据状态给出下一步

首页/能量页显示轻量流程条：计算日志 → 反应路径 → 检查能量 → 保存/导出。各步显示“待开始、需处理、可继续”，不使用随便存入项目的 completed 布尔值。每步状态从实际项目、当前修订计算结果、来源连接和保存状态推导。

| 实际状态 | 主提示与按钮 | 次操作 |
|---|---|---|
| 无项目 | “开始一个研究项目”/新建项目 | 打开项目、导入日志并创建项目 |
| 有项目，无来源 | “先加入计算日志”/导入日志 | 打开搭建器建立缺值占位 |
| 已导入，尚未建成配方 | 导入摘要/选择作业并搭建路径 | 查看所有计算日志、保留现有普通路径 |
| 路径有缺项 | “有 N 项需要处理”/继续编辑 | 逐项定位、查看来源 |
| 当前结果有效，项目未具名 | 保存项目 | 查看图表、导出 |
| 项目已保存且当前修订一致 | 查看图表/导出 | 继续编辑 |
| 忙碌、只读或来源失效 | 对应文字原因及可行动作 | 取消任务、另存为、重新定位来源 |

导出不是保存项目的替代品。来源失效时可查看历史结构和元数据，但不能把旧能量标成当前有效。

### 3.4 一条具体使用流程

1. 首页点“新建项目”，填名称；不强制立即选保存目录。
2. 点“导入日志”或拖入 .log/.out，显示文件名、作业数、可用 SCF/热校正、异常状态与导入结果。用户可直接打开计算日志页。
3. 点“选择作业并搭建路径”，对多作业文件明确选择 job；同名文件用短 UUID 与文件路径区分，不按名称合并。
4. 进入搭建器，拖物质卡至阶段，选择反应物/中间体/TS/产物角色，连接阶段；也可用“加入阶段”和“连接到…”完成相同操作。
5. 为阶段选择“一个完整体系作业”或“多个独立组分”，明确组成与能量账本；显示当前待核对事项。
6. 选择零点，查看完整反应式、统一零点的相对能量、局部步差和来源；缺项可点提示跳回对应字段。
7. 点“应用并保存”，一次进入预检 → 提交项目修订 → 写盘。首次保存才选文件路径；失败保留数据并给出重试。
8. 成功后“返回能量图”直接显示该路径，选择、颜色、星标和零点与搭建器一致。

步骤引导可以随时返回。查看来源和调整界面不清空已填写内容。不用强制全屏教学遮罩、每步弹确认框或长篇首次启动教程。

## 4. 可视化路径搭建器

### 4.1 布局与职责

继续使用 ReactionBuilderDialog 作为控制器入口，将长构造函数拆为组件，不创建第二份科学项目。

~~~text
项目名 / 路径名         草稿有修改       [撤销][重做] [帮助]
搭建路径    检查能量    保存结果                    能量口径 ▼
┌物质库─────────┬阶段画布──────────────────┬选中项详情──────┐
│搜索/星标/来源  │ [反应物 A+B] → [TS] → [产物 C+D] │角色、名称       │
│物质卡、作业徽章│             ↘ [中间体/分支]      │组成/能量来源    │
│新增/批量建卡   │ [＋阶段]  [适应画布]              │系数、边、核对   │
│               ├完整反应式 / 零点 / 能量预览──────┤来源证据可展开   │
└───────────────┴─────────────────────────┴────────────────┘
有 2 项需要处理 [逐项查看]        [保留草稿并关闭] [应用并保存]
~~~

视觉画布表达阶段拓扑；独立的“能量预览”表达真实计算纵坐标。两者清楚标注，阶段画布的位置不能被解释为能量高低。

左栏约 240 DIP；右栏约 300 DIP；中间伸缩。宽度不足 1180 DIP 时右侧改为可收起抽屉。840×680 下物质库与详情可切换抽屉，画布与底部主操作保持可见。每个长面板自身滚动，整个窗口不得被表单的最小高度撑出屏幕。

### 4.2 物质卡

卡面仅显示：名称、可选分子式、来源/作业简写、能量可用状态、星标。UUID 全值、原始路径、方法/基组、温压、SCF/热校正原文和行号在详情中展开。

点卡片显示详情；点星形按钮加星，星标只改变物质检索/标记。拖动卡片不会隐式改星标。允许搜索名称/来源，按星标和“能量可用/待绑定”筛选。

“从已导入作业创建物质卡…”显示候选表，让用户一次选择若干明确 source/job，再逐项确认名称。无歧义时只预选，不绕过确认；多作业不按最后一个作业猜测。只有选中的绑定入库，同名不合并。

无来源卡显示“待绑定”；可用于反应式草稿，但不可产生有效能量。拖卡至阶段后需要明确选择能量来源方式，不自动把反应式的系数照抄为能量系数。

### 4.3 阶段卡与连接

阶段卡显示：角色徽章、标签、组成缩写、能量配置状态、诊断数量、是否为零点。TS 的形状/文字与一般阶段可区分；不能只靠颜色。

卡片右下提供“+ 后续阶段”和“更多”。选中后在详情修改；双击标签改名。空白画布有“添加反应物阶段”提示，右键仅为辅助操作。

实现使用 Qt QGraphicsView/QGraphicsScene；StageItem 与 ConnectionItem 的身份取现有 stage/connection UUID。移动卡片只改变布局，不改变 PathEntry 顺序、前驱集合或科学值。布局坐标与画布缩放保存在 ux_v2 的展示数据中，不写进 reaction_network_v1 的严格字段。

从输出端口拖到另一阶段输入端口，或“连接到…”弹出目标列表。合法候选高亮，非法候选显示“会形成环/阶段不存在”等原因。放开后创建一条待核对边；不自动把它设为已确认。删除边可撤销。新分支显式选择共同前驱；回汇显式指定全部入边，沿用现有拓扑验证与递推一致性检查。

拖物质到“阶段组成区”有清晰落点和幽灵预览；拖到“能量来源区”打开绑定/系数选择。放错区显示原因并保持草稿不变。阶段已含同一物质时选中既有项，不静默增加或覆盖系数。插入阶段不自动改所有旧边；先预览将断开/新增的连接，确认一次后提交本地命令。

物质关系网与当前路径的阶段连接是两类关系，分别标明“物质邻居”和“本路径连接”；不能用同一条边暗中同时写两种数据。关系网部署先展示候选，再进入草稿，不自动应用项目。

### 4.4 基础视图与高级视图

基础视图默认显示角色、组成、能量来源、零点和待处理项。高级折叠区放有符号能量项、边局部差递推、额外补偿项、专家 AST 和技术编号。折叠仅改变呈现，不能隐藏会影响有效性的未解决错误。

阶段能量配置使用两个清楚的选项卡：

- 一个完整体系：明确选择一个 job；预览该 job 含有的完整体系，不自动再加图示游离物质。
- 多个独立组分：用可编辑行显示每项作业与系数；总和由现有表达式接口产生。额外补偿项与负系数进入高级区并填写原因。

每个阶段在同一面板并排显示“反应式组成”和“用于计算的能量项”。说明不同口径为何存在，让用户核对后确认，不能以减少点击为由删掉现有 normalization_confirmed、逐边确认或解释字段。

确认项有变更即失效：修改组成、绑定、系数、口径、前驱或零点签名时，清除对应阶段/边的旧确认，并列出原因；名称、画布位置、主题不使科学确认失效。仅在详尽预览后逐项确认，禁止默认勾选“全部正确”。

### 4.5 旧项目与复杂表达式

打开搭建器时必须先分类，不直接展示空白窗口：

| 当前路径 | 要求 |
|---|---|
| 有有效 reaction_network_v1 配方 | 按原 UUID、阶段、边、零点和账本加载，展示已有物质关系 |
| 路径无节点 | 显示新路径空状态与“添加阶段/从日志创建物质卡” |
| 有普通节点但无配方 | 画布先显示现有节点和原表达式/值的只读概览；提示“这条路径尚未配置可视化阶段” |
| 有复杂 AST、直接差值或无法无损转换的节点 | 明确显示“使用专家表达式”；提供打开既有 expression_editor.py::ExpressionDialog；不能把它简化为一个来源引用 |

为普通路径提供“转换预览…”：支持范围固定为标准体系表达式中的单个 EnergyRef，且无无效草稿、无组合 Gibbs 模板、无手工偏移。保留原 node/entry UUID；按当前路径能量类型与同一 source/job 建议能量项。用户选择角色和组成、确认固定能量类型策略；预览必须比较转换前后的绝对能量、参考能量、相对能量与来源依赖。单纯的导入顺序只作画布排列，不自动声称为已确认反应边。

原位转换还要求现有路径为 relative 模式，参考表达式的 reference_signature 与某个已有节点体系表达式一致，从该节点建议零点；参考是其他组合式/手工值/无效草稿时不自动原位转换。无论节点值恰好相等与否，都不通过“数值碰巧相等”识别零点。未指定角色先显示“待选角色”的 UI 状态，用户明确角色后才生成可校验的网络阶段。

当前核心默认重建 node/entry UUID，因此原位转换的身份保留需要 U3 的显式 identity_policy 接口，不可只在 UI 中填好 ID 然后声称已经保留。共享于其他路径的 node 不符合 preserve_exclusive；这种路径本次选择另建独立路径，保留原有共享语义，不静默修改其他路径。

只要路径中有一项不在上述支持范围，整条路径不能自动原位转换。提供“继续用专家编辑器”和“选取可用作业另建可视化路径”；后者明确列出保留/未采用项并创建新 path UUID，原路径不变。不得为了支持复杂旧 AST 而扩展或绕过现有科学网络格式。

转换预览是草稿：取消不改变项目、引用策略、零点、节点和来源。原位转换正式应用与用户创建配方一样必须通过既有核心验证，不能仅凭两次浮点数相等判为语义等价。

## 5. 能量预览、零点和就地纠错

### 5.1 科学值展示

保持旧 L4 科学规则：Gibbs 总量为同一 source/job 的 SCF Done + Thermal correction to Gibbs Free Energy；两条来源行都保留。SCF、单独热校正与 Gibbs 总量明确命名。默认常用预设可选“Gibbs 相对能量”，选择 SCF 模式是用户显式动作；缺热校正不能自动降级 SCF。

结果表固定列：阶段、角色、体系绝对能量/Eh、相对所选零点/kcal·mol⁻¹（或当前单位）、局部前驱、相对前驱的步能量、状态。只有满足核心资格时称为“局部势垒”，不能把所有相邻差值称作势垒。

主图用统一零点累计能量；局部差另列。表/图上同时注明能量量纲、零点来源、当前修订，以及“草稿预览/已应用项目结果”。零点从阶段、组合表达式或高级手工值中选择；阶段可点“设为零点”，显示可撤销的修改摘要。

缺值显示“— / 缺少热校正”等文字；NOT FOUND TS 只作缺值状态卡。一个真实的 0.000 值必须由有效结果产生，不能以真假判断把 0 当作缺值。参考变更后全部有效纵坐标同步平移，绝对值与来源不变。

卡片/字段改变后立即使旧预览失效，显示“待重新检查”；不用旧值维持看似平滑的曲线。轻量本地结构检查可立即做，计算预览通过既有串行后端核查来源；不得在 GUI 主线程读大日志或跑全项目计算。

### 5.2 检查清单

将当前一个长错误字符串整理为结构化列表，每项至少带 code、严重性、path/stage/connection/species ID（适用时）、短说明和建议动作。详情点击后选中目标并滚动至对应字段；纯文件错误跳计算日志页并定位该来源。

示例文案：

| 问题 | 面向用户的表达与动作 |
|---|---|
| 热校正缺失 | “TS1 所选作业缺少 Gibbs 热校正。请选择有该数据的作业，或显式改用 SCF 模式。”/选择作业 |
| 来源 SHA 变化 | “A 的日志内容已改变，本次能量不可作为当前结果。”/重新定位并核查 |
| 完整体系重复加组分 | “该阶段使用完整体系作业，同时加入 B；请核对是否重复计算。”/查看能量项 |
| 归一/边未核对 | “IM2 → TS2 尚未确认组成与共同参考。”/核对这条边 |
| 回汇冲突 | “两条入边得到的累计能量不一致。”/查看两条入边和差值，不自动取平均 |
| 项目只读 | “当前项目以只读方式打开。”/另存为可编辑副本 |
| 项目修订已变化 | “项目已被其他操作更新，请重载或保留草稿。”/保留草稿、重新加载 |

错误阻止应用；警告列明后允许用户继续的范围由现有核心规则决定；信息项不阻塞。使用图标、文字和数量徽章，颜色只是辅助。

## 6. 项目命名、保存与草稿

### 6.1 名称语义

继续采用“已保存项目名 = .grproj 文件名去扩展名”。本次不新增独立 Project.name 字段。新建/未保存时的名称写在 workspace_state["ux_v2"]["pending_project_name"]，用 controller.set_workspace 合并，保持恢复副本可携带它；先在 UI 反馈，再等待既有工作区提交。

未保存项目点重命名：只改此暂存名称，提示“将在首次保存时作为文件名”。已保存项目点重命名：显示同目录目标路径，通过现有 controller.rename_project / SessionBackend.rename_project 执行。只改大小写的文件名本次明确提示暂不支持，不伪报成功。输入与原名称完全相同是无变化操作。

名称去首尾空白，1–120 个字符；不允许控制字符、Windows 非法字符、路径分隔符、结尾点/空格，以及 CON/PRN/AUX/NUL/COM1–9/LPT1–9 等保留名（大小写不敏感，带扩展名仍拦截）。.grproj 作为固定扩展名展示，不要求用户输入；界面预检后后台仍验证完整目标路径、存在性和权限。长路径无法访问时显示操作系统错误并保留输入。

改名只在后台成功后更新路径、最近列表和标题；失败保留旧状态。非当前最近项目改名不改变当前项目。删除、最近移除和改名是不同操作，删除确认继续展示完整路径和影响范围。

### 6.2 保存状态

头栏显示以下准确状态：尚未保存、未保存更改、保存中、已保存、保存失败、只读。恢复副本另标“已保留恢复副本”，不把它显示成主文件已保存。状态依据 SaveStatus 的修订号和 error 字段计算，不能用点击按钮或 controller.save() 的 bool 代表落盘成功。

修复 _pending_project_name 提前清空：只有任务成功且具名目标对应的 saved_revision 已覆盖目标修订，才结束首次保存流程。取消文件选择、拒绝任务和写盘失败均保留名称与编辑内容。后续的新修改可高于已写盘目标修订，此时显示“仍有未保存更改”。

最近项目首页提供可见“更多”按钮或明确标注的选中项操作栏，至少包含打开、重命名、从最近移除、删除文件；键盘能进入。右键继续保留为快捷入口。

### 6.3 应用并保存的状态机

主按钮为“应用并保存”；旁边菜单保留“仅应用到当前项目”“仅保存物质与关系网…”等高级动作。网络单独保存仍须明确影响，不与整条路径应用混称。

~~~text
编辑草稿 → 校验来源与计算预览 → 等待用户处理阻塞项
         → 应用到目标项目修订 →（首次：选择文件路径）→ 保存指定修订
         → 成功 / 已应用但尚未保存 / 保存失败可重试
~~~

以 project UUID、path UUID、draft generation、base revision 和操作 token 关联每次请求；只消费对应的后台完成事件。失败或无关 busyChanged 事件不得推动下一步。重复点击不得提交两个应用，过期回调不得关闭窗口或标成功。必须在状态消息里区分“修改已应用到内存项目，文件保存失败”。

首次文件选择取消：保留已应用修订，显示“已应用，尚未保存”，主按钮改为“保存项目”；再次点按不能重复创建路径/节点。保存失败只重试写盘，草稿若再次修改才重新预检和应用。目标项目发生切换或内容修订冲突时中止后续写入并保留草稿。

### 6.4 草稿退出、撤销与恢复

草稿初始无改动。任何语义修改进入本地撤销栈，最多 100 条；拖卡、建边、更新一组系数各是一条可撤销命令。撤销不会写科学项目；全局项目撤销与编辑器本地撤销各有清楚作用域，输入框自身 Ctrl+Z 优先处理文本。

关闭按钮、Esc、取消、窗口 X、切换到另一条路径都经过同一脏草稿守卫：“继续编辑”“保留草稿并关闭”“放弃草稿”。未改动直接关闭。切换路径也不能默默丢弃当前草稿。

“保留草稿”由 SessionBackend 的同一个串行 worker 写到 recovery_directory 下 ux-drafts/<project_uuid>/<path_uuid>.json。文件记录 format=gaussianreadpro.builder-draft、version=1、项目/路径 UUID、基础 revision、draft generation、network 草稿、展示布局；大小限制 2 MiB，不写原始日志内容。使用同目录临时文件和原子替换，失败不关闭窗口。格式/大小/UUID 校验在写入和读取两侧执行，不能由输入名称拼接路径。

本次不要求逐键盘输入自动写草稿。已有程序恢复副本、具名项目保存和这个“尚未应用的编辑草稿”各自标明用途。再次打开时可恢复或放弃；基础 revision 不一致时只允许先预览并重校验，不自动覆盖当前项目。已应用且成功保存的同 generation 草稿可清理，失败不得删。只读项目可查看和导出草稿文本，不对主项目自动写入。

## 7. 可访问性、视觉反馈与操作细节

1. 主操作用文字；图标必须有 tooltip 和 accessibleName。正文与背景目标对比度 4.5:1，关键图形/边界 3:1；状态不能只靠颜色。
2. 阶段、物质、能量项的删除有本地撤销即可，不每次弹确认；删除项目文件和丢弃未保存草稿继续明确确认。
3. 拖动以 6 DIP 移动阈值区分点击；提供合法落区高亮、吸附预览和无效原因。拖动取消/Esc 不改变草稿。减少动态效果时保留静态落区反馈。
4. 键盘可在物质列表、阶段列表/画布、详情、问题清单与页脚间按 Tab 移动；阶段用方向键选择，Enter 打开详情，Delete 执行可撤销删除。所有拖拽能力均有按钮替代。
5. Ctrl+S 在搭建器中触发“应用并保存”，主窗触发项目保存；避免两者同时响应。新增 Ctrl+Shift+E 打开/聚焦反应路径编辑器，菜单显示快捷键。
6. 切换主题、语言或窗口尺寸不得重建草稿、改变 AST、清零选择或重置相机。新增 builder 文案进入现有 zh_CN/en 字典；不能像现有构造函数一样大量新增未翻译字面量。
7. 已有星标物质在卡片与路径点一致；图上右键先选择相关物质，不能把“节点”冒充一种物质。空白画布不误触发物质操作。
8. 忙碌时在控件附近显示“正在导入/检查/保存”，禁用原因可读；取消操作仅用于实际可取消的任务，不能伪装取消已执行的文件重命名。
9. 840×680、1100×820、1440×900 逻辑尺寸；DPR 1/1.5/2，CN/EN、浅/深色都保证主按钮可达。长名不挤出保存与关闭。

## 8. Luna 的代码边界与接口约定

下面为计划新增接口，不是声称源码已有。实施中需改名时先同步本节和依赖任务，不各自另起接口。

### 8.1 复用的入口

| 能力 | 现有接口/文件 |
|---|---|
| 项目/来源/科学修改 | ProjectController 及 SessionBackend；不在 QWidget 中直接 os.rename/unlink 或写 SQLite |
| 打开搭建器 | MainWindow.open_reaction_builder(path_id=None, node_id=None, entry_id=None) |
| 正式应用 | ProjectController.apply_reaction_recipe(network, path_id, new_path=None, path_options=None)；U3 增加可选身份策略，见下文 |
| 网络验证/生成 | read_reaction_network、validate_network、apply_path_recipe、reference_signature |
| 当前值与审计 | calculate_path → build_plot_spec → plot_payload；来源核查沿用 SessionBackend.view |
| 保存结果 | controller.statusChanged 的 SaveStatus；具体来源核查/保存仍在后台 |
| 图表桥接 | ProfilePanel._valid_envelope、workbench_action；遵守现有 project/revision/render_id 检查 |

### 8.2 计划文件

| 新增/调整文件 | 单一职责 |
|---|---|
| ui/project_actions.py（新增） | 共享 QAction：new/open/import/save/save_as/rename_project/edit_reaction_path；菜单、按钮和快捷键使用同一动作 |
| ui/workflow_state.py（新增） | 纯派生 WorkflowSummary/ActionAvailability/保存状态文案；无文件 I/O、无科学数值求值 |
| ui/reaction_builder_state.py（新增） | BuilderDraft 的本地编辑、generation、dirty、undo/redo、问题定位、旧路径分类/转换建议 |
| ui/reaction_canvas.py（新增） | QGraphicsScene 卡片/连线/落区；只发 UUID 意图，不自行修改 network 或计算能量 |
| ui/reaction_stage_inspector.py（新增） | 选中阶段/边的字段、来源和核对呈现，通过 draft 命令更新 |
| ui/reaction_builder.py（调整） | 组合上述组件、阶段导航、操作状态机及统一退出守卫；既有内部方法逐步改为调用共享 draft |
| services/builder_drafts.py（新增） | 草稿 JSON 编解码、2 MiB 限制、原子文件读写；由 SessionBackend 调用 |
| services/controller.py、session.py（调整） | 为请求提供可关联的完成信号与显式预览/草稿读写；同一个串行 worker |
| core/reaction_network.py（限 U3 身份接口） | 增加 preserve_exclusive 物化身份策略；默认仍 regenerate，不改任何表达式求值、计量或零点算法 |
| ui/main_window.py（调整） | 常驻头栏/能量操作栏、稳定路由、导入摘要及名称状态；移除冲突的显隐规则 |
| resources/plot/replica_controls.js、profile.html、ui/profile_view.py | 网页已有编辑入口统一转发共享 QAction；不增加 JS 求值；离线隐藏/禁用编辑动作 |
| resources/locales/zh_CN.json、en.json、theme.py | 新文案、焦点、错误/落区/高对比样式；复用现有 tokens |
| tools/audit_v1_bundle.py、当前桌面验证脚本 | 检查新模块、真实可见入口、截图与包资源哈希 |

### 8.3 共享接口

- MainWindow.activate_route(route: str) -> None：固定接受 home、sources、path_nodes、energy；映射到现有索引和 compact_tabs，不改变旧 page 编号。
- ProjectActions.action(key: str) -> QAction：未知 key 抛 ValueError；状态通过 set_availability(key, enabled, reason) 更新；后台保护仍保留。
- derive_workflow(project, results, connections, save_status, *, active_path_id, busy, read_only) -> WorkflowSummary：仅使用当前 project UUID/revision 的结果。输出 next_action、各步状态和待处理数量；不根据是否有文件名猜计算有效性。
- BuilderDraft.from_project(project, path_id) -> BuilderDraft：保存 base_project_id/base_revision/path_id、network 与展示布局；明确 existing_recipe/empty/legacy_supported/legacy_expert 分类。
- BuilderDraft.execute(command: dict) -> None、undo()、redo()、snapshot() -> dict：command 使用明确白名单；每个改变增加 generation 并清除受影响确认/旧预览。画布只调用这些接口。
- ReactionCanvas.set_draft(snapshot: dict) -> None；selectionRequested(kind, uuid)、commandRequested(command) 信号。程序刷新不回发第二个修改命令。
- apply_path_recipe(project, raw_network, path_id, *, identity_policy="regenerate") 及 ProjectController.apply_reaction_recipe(network, path_id, new_path=None, path_options=None, *, identity_policy="regenerate")：仅接受 regenerate/preserve_exclusive。后者只在 stage 所带 node_id、entry_id 同时对应目标路径的一个现存 PathEntry，且 node 没有被其他路径引用时复用二者；新阶段两者均为空才创建新身份。只填一个、悬空、重复映射或共享 node 均拒绝，不默默回退。节点内容按同一现有算法生成，复用 node 的 display 数据保留；科学公式不变。新建独立路径使用 regenerate。
- ProjectController.preview_reaction_recipe(network, path_id, *, new_path=None, path_options=None, identity_policy="regenerate", draft_generation: int) -> int | None：返回提交任务的 int token；信号 reactionPreviewReady(token, project_id, base_revision, draft_generation, prepared_project, results, diagnostics)。预览与正式应用使用同一个身份策略。执行前通过后台检查当前来源；响应必须匹配当前草稿，禁止覆盖过期预览。
- ProjectController.operationFinished(token: int, operation: str, success: bool, project_id: str | None, revision: int | None, path: str | None) 信号：由既有 _completed 发出，给应用并保存状态机和首次命名流程使用；任务提交 bool 语义保持不变。需要记录提交 token 时新增只读 active_task_token 属性，不能由视图读写 _active。每个完成的已提交 token 仅发一次；失败、取消和过期结果均不得发 success=True，返回身份对应提交时的目标，不以当前另一项目冒充。
- SessionBackend.save_builder_draft(payload: dict) -> Path、load_builder_draft(project_id, path_id) -> dict | None、remove_builder_draft(project_id, path_id, generation) -> bool：固定 UUID 路径、串行执行；corrupt/oversize 返回结构化 StorageError，不将坏草稿应用项目。

预览草稿来源核查时，使用当前后台会话得到的来源快照；不得对已改 SHA 的日志只使用之前缓存 job.energies。上面新预览接口只组织旧验证链，不新写公式求值逻辑。

工作区展示键统一用 workspace_state["ux_v2"]，包含 version=1、pending_project_name、builder_layouts（按 path UUID）、last_builder_step。嵌套更新合并现有值，不覆盖 page、path_id、widths、reaction_network_v1 等旧键。输入坐标只接受有限数、绝对值不超过 100000 DIP，未知/坏布局退回自动排布；布局键不作为反应拓扑依据。

### 8.4 草稿命令与派生状态的最小契约

ActionAvailability 字段固定为 enabled: bool、reason_code: str | None、reason_text: str；WorkflowSummary 字段为 steps（固定 sources/path/check/save 四项）、next_action（第 8.2 节共享动作 key 或 None）、issue_count: int、save_state（第 6.2 节状态枚举）。步骤状态只取 pending/needs_attention/ready，显示时翻译，不存为项目事实。

BuilderDraft.snapshot() 返回可 JSON 编码的 project_id、base_revision、path_id、generation、network、layout、path_options、legacy_mode；不带 QObject/Project/MappingProxy 实例或日志正文。脏状态比较初始可序列化快照，不以选中项/滚动变化判为科学修改。

execute 的 command 固定使用 type 字段；第一版白名单为 add/update/remove_species、set_star、add/update/remove_stage、set_composition、set_energy_terms、add/update/remove_connection、set_zero、set_path_options、move_stage。统一 payload 带目标 UUID；composition/terms/connection 的字段复用现有网络字典格式；move_stage 只带 stage_id/x/y，set_star 只带 species_id/starred。未知命令、未知字段、跨项目 UUID、重复连接和非有限坐标先拒绝，network/布局/撤销栈保持原样。

一次命令先在副本上做局部结构检查，成功后一次替换并写一条 undo 记录；redo 在新命令后清空。草稿允许未配置作业、未核对边等未完成状态，不能为了通过 validate_network 自动勾选核对。完整核心校验只在预览/应用时做；局部命令只阻止无效身份、非法字段和环等不可编辑结构。数值预览与科学确认字段的失效规则按第 4.4/5 节；move_stage 和选中/滚动不改变科学确认和已显示数值。

## 9. 分阶段实施计划

所有任务按下面“小步失败用例 → 最小实现 → 相关验证 → 报告”执行。U0–U8 已完成；U7 源码路线与 U8 冻结包限制分别见 `docs/ux-v2-u7-validation.zh-CN.md`、`docs/ux-v2-u8-validation.zh-CN.md`。不得在一个补丁里重写整个 MainWindow 与全部科学核心。

### U0：复现与基线（不改业务）

文件：新增 docs/ux-v2-baseline.zh-CN.md；桌面脚本放 tools/check_ux_v2.py。

- [x] 从 AI_HANDOFF/docs/handoff 确认源码、入口、当前可用 EXE 路径，记录版本与实际 EXE SHA；不使用历史截图证明当前程序。
- [x] 分别打开无项目、已导入普通路径、有配方路径；记录 F01–F12 的实际表现、窗口截图尺寸和唯一显示器 Qt DPR。冻结窗口的 widget DPR 未由 Computer Use 直接暴露，报告标明测量依据。
- [x] 点击默认能量页能看到的“+”、设置、最近菜单；记录可辨认的实际对话框/下拉路由及未暴露的菜单类，不直接调用内部函数代替用户操作。
- [x] 证明 ReactionBuilderDialog 与 reaction_network 模块是否存在于当前冻结包；当前包含模块但早于当前 U1–U6 源码，报告区分源码入口与包版本差异。
- [x] 做一次新建名 → 首次保存失败/取消的受控复现，记录名称是否丢失；仅使用 artifacts/ux-v2 下合成项目。

交付：现象/证据表，给 U1/U2 写实际回归断言。缺桌面工具时明确缺哪项，继续可做的源码/单元工作，不能宣称不存在 Windows 桌面。

### U1：恢复并统一入口

文件：project_actions.py、main_window.py、profile_view.py、相关 locales；新增 tests/test_workflow_actions.py。

接口：第 8.3 节的 ProjectActions、activate_route。

- [x] 用例 test_default_energy_view_has_visible_builder_and_save_actions：从 MainWindow 默认路由检查有文字的搭建/保存/项目名控件确实在可见祖先链中；不是只检查对象存在。
- [x] 用例 test_chart_fallback_keeps_native_builder_entry：网页不可用时原生入口仍可点。
- [x] 创建共享 QAction，统一菜单/按钮/快捷键；无项目时点击编辑器导向新建项目选择，不再静默 return。
- [x] 删除 _sync_replica_shell 与 resizeEvent 对主操作的冲突 hide/setVisible；恢复计算日志导航；各尺寸在一个渲染规则中决定溢出。
- [x] 主图常驻“编辑反应路径”；切换能量图/节点表可双向返回，不依赖先打开设置；原有图表选择与相机保持。
- [x] 新建路径默认进入完整搭建流程；原有已有节点勾选对话框作为明确的高级菜单项。
- [x] 跑新动作测试与 tests/test_multi_paths.py；桌面脚本至少从可见按钮点开一次真实 ReactionBuilderDialog，并检查活动 path UUID。

U1 验收记录：[`docs/ux-v2-u1-validation.zh-CN.md`](ux-v2-u1-validation.zh-CN.md)。U1 当时 U0 未完成；当前 U0–U8 源码与发行包阶段均已记录完成。

通过标准：从默认主图一次点击进入当前路径搭建；项目名/保存随页面与窗口变化始终可达。此阶段不必等画布完成才交付入口修复。

### U2：项目名、最近项目与保存反馈

文件：workflow_state.py、main_window.py、controller.py、session.py、locales；新增 tests/test_project_management_ux.py。

接口：operationFinished、active_task_token；复用现有 rename_project，不在 UI 执行文件操作。

- [x] 覆盖未保存项目改名、具名项目改名、最近非当前项目改名、目标已存在、非法/保留名称、文件占用失败、取消及只读。
- [x] 用例 test_first_save_failure_keeps_pending_name：失败、取消、拒绝提交后名称不丢；saved_revision 未确认前不显示成功。
- [x] 用例 test_rename_does_not_change_uuid_or_scientific_state：比较 UUID、AST、来源、相对能量与最近列表；失败后旧路径可继续用。
- [x] 项目名按钮和最近列表可见更多操作；状态严格采用第 6 节，区分主文件保存与恢复副本。
- [x] 暂存名称迁入 ux_v2 工作区，兼容旧内存字段；嵌套合并不覆盖其他工作区数据。
- [x] 运行本阶段测试及现有 tests/test_workbench.py 中项目生命周期/保存失败用例；本机桌面验证覆盖首次保存取消/失败/重试与当前/最近项目改名。
- [x] 840×680 时将“继续研究”卡片置顶，使最近项目操作位于可视区；高窗口保留原顺序。验收记录：[`docs/ux-v2-u2-validation.zh-CN.md`](ux-v2-u2-validation.zh-CN.md)。

通过标准：用户不用设置菜单或右键就能改名；失败不丢输入、不改错文件、不错误报成功。

### U3：导入后引导与旧路径兼容

文件：workflow_state.py、reaction_builder_state.py、main_window.py、reaction_builder.py、controller.py、core/reaction_network.py；新增 tests/test_builder_legacy_adapter.py。

接口：derive_workflow、BuilderDraft.from_project；只提出转换草稿，不直接改 project。

- [x] 导入摘要显示文件/job 数与能量可用状态，入口跳到作业候选表；现有导入节点保留。
- [x] 从空项目/普通单引用路径/有配方路径/复杂 AST/绝对能量/直接差值/无效草稿分别创建视图；旧路径不再表现为凭空空白，非支持路线可选作业另建相对能量路径。
- [x] test_supported_legacy_conversion_preserves_values_and_ids：单 EnergyRef 转换预览，核对 node/entry UUID、绝对/相对/参考值和依赖；引用策略变化在确认中明确显示。
- [x] 先为 apply_path_recipe 增加默认兼容的 identity_policy：test_default_materialization_still_regenerates、test_preserve_exclusive_reuses_only_valid_entry_node_pairs、test_shared_node_conversion_requires_new_path。预览与正式应用策略一致；现有未显式传参的调用行为不变。保留独占 node 的 display 数据，新阶段正常生成 UUID；不得改求值算法。
- [x] test_complex_ast_is_not_silently_rebuilt：拒绝自动原位转换；取消或另建路径后原 AST/参考与原路径保持。
- [x] test_import_does_not_auto_confirm_reaction_edges：文件顺序和标签不生成已确认的反应边；多 job/同名来源必须明确选择 UUID。
- [x] 建立物质卡/阶段提案与“继续查看原路径”两条路线；不要把所有导入作业默认当成同一反应。
- [x] 跑本阶段测试、现有表达式/反应网络测试；用合成项目与 Windows 原生 Qt 后端检查旧路径首次打开说明和无修改退出。验证记录：docs/ux-v2-u3-validation.zh-CN.md。

通过标准：已有数据看得见；普通路径可在明确确认后采用新编辑器；复杂路径不被简化或覆盖。

### U4：可视化阶段画布与局部详情

文件：reaction_canvas.py、reaction_stage_inspector.py、reaction_builder_state.py、reaction_builder.py、theme/locales；新增 tests/test_reaction_canvas.py。

接口：BuilderDraft 命令/撤销、ReactionCanvas 信号；不修改科学数据模型。

- [x] 将原窗口拆为物质库、阶段画布、详情、预览和页脚；原列表可保留为键盘替代视图，不能维护第二份 network。
- [x] test_move_stage_changes_layout_only：移动卡片前后 AST/拓扑/能量一致；test_connect_rejects_cycle：无效连接不落草稿。
- [x] test_drop_targets_do_not_mix_stoichiometry_and_energy：组成区与能量区有不同反馈；没有绑定不自动生成能量项。
- [x] test_one_gesture_is_one_local_undo：一次拖入/建边/删除/系数组修改各能一次撤销；撤销回到相同 network。
- [x] 提供角色卡、零点徽章、缺值 TS、分支/回汇连线、选中详情；新增边仍待用户核对。
- [x] 修改科学组成时清除受影响确认；布局/文字改名不清除科学确认，依第 4.4 节固定范围做用例。
- [x] 在 840×680 实际窗口验证主按钮与字段可达；阶段列表可切换为键盘替代视图。字段在窄窗内可滚动访问；验收记录：[`docs/ux-v2-u4-validation.zh-CN.md`](ux-v2-u4-validation.zh-CN.md)。

通过标准：不用打开隐藏表单即可看懂阶段与连接；拖动的含义有预览；画布位置与能量坐标不混淆。

### U5：能量检查与可靠的应用/保存

文件：controller.py、session.py、reaction_builder.py、reaction_builder_state.py、workflow_state.py；新增 tests/test_builder_save_flow.py。

接口：preview_reaction_recipe/reactionPreviewReady、operationFinished；沿用 apply_reaction_recipe、SaveStatus。

- [x] 将同步 _preview 的来源核查/计算组织到现有串行 worker；当前草稿 generation 匹配后才接受结果。
- [x] test_changed_source_invalidates_preview：SHA 改变、文件缺失、修订变化都不能拿旧缓存值显示可应用。
- [x] 用受控同作业 SCF+热校正验证 3 阶段绝对值 −10/−9.98/−10.02 Eh，反应物零点相对值 0/+0.02/−0.02 Eh；产物零点 +0.02/+0.04/0 Eh。来源两条行号、局部差与固定单位换算都核对。
- [x] 建立可点击的诊断清单；NOT FOUND 不能写有效值，合法的零值必须显示。
- [x] test_apply_save_cancel_then_retry_does_not_duplicate_nodes、test_save_failure_retries_io_only、test_unrelated_completion_cannot_finish_save、test_stale_preview_is_ignored：严格按第 6.3 节的 token/修订状态机验证。
- [x] 主按钮串联预检、应用、首次选择路径、写盘；“仅应用”仍可用，状态文案与动作范围一致。
- [x] 跑本阶段测试、tests/test_s8_flow.py 和现有反应网络/来源/保存回归；桌面实测成功和一次受控保存失败。多场景 Qt 测试进程中止按限制记录；逐项隔离运行通过。验收记录：[`docs/ux-v2-u5-validation.zh-CN.md`](ux-v2-u5-validation.zh-CN.md)。

通过标准：用户可一条操作完成常见保存；任何失败都不把未保存内容标成功，也不重复构建节点。

### U6：草稿保护、键盘与适配

文件：services/builder_drafts.py、session.py/controller.py、reaction_builder.py、locales；新增 tests/test_builder_drafts.py。

接口：第 6.4/8.3 节草稿方法、统一退出守卫。

- [x] 测关闭、Esc、取消、路径切换的脏草稿分支；继续编辑、放弃、保留的实际效果一致。
- [x] 测草稿格式损坏、超过 2 MiB、路径 UUID 非法、目录不可写、保存中断；失败窗口不关闭，旧有效草稿不被破坏。
- [x] 新进程恢复同 UUID/同 revision 草稿；不同 revision 先提示冲突与重校验；不得恢复成已应用状态。
- [x] 完成 Tab/方向键/Enter/Delete 操作与 Ctrl+S 作用域；输入框 Ctrl+Z 不同时撤销整个阶段。
- [x] CN/EN、light/dark、减少动效与尺寸变化保留草稿；诊断定位会滚动并聚焦错误阶段字段。
- [x] 跑本阶段测试；DPR 1/1.5/2 原生桌面矩阵记录实际窗口、焦点顺序、按钮文案宽度和 36 张截图。DPR 2 的 8 个大尺寸窗口受当前屏幕逻辑边界约束，详见 [`docs/ux-v2-u6-validation.zh-CN.md`](ux-v2-u6-validation.zh-CN.md)。

通过标准：退出不意外丢编辑；不靠鼠标拖拽也能完成路径；窄窗可操作。

### U7：真实用户路线、冻结包与交接

文件：tools/check_ux_v2.py、tools/audit_v1_bundle.py、相关验证报告与交接文件；打包仅在用户要求交付包时进行。

- [x] 用真实日志（来源与许可可追溯）验证解析/作业选择/来源行/保存重开；另用清楚标明合成的非零 3 阶段夹具验证形状和计算，不拿相同能量真实日志证明势垒。
- [x] 从默认首页开始，通过实际可见按钮完成新建/改名/导入/搭建/零点/预检/保存/能量图/导出，不以直接调用 _add_stage/_apply 代替路线验收。
- [x] 使用含 B 的结构核对符号，在搭建器给物质加星；建两条不同颜色路径，保存并用新进程重开，核对 UUID、AST、零点、物质关系和图表状态。
- [x] 有配方旧项目、无配方普通项目和专家 AST 项目各一条兼容路线；覆盖保存失败、草稿退出/恢复、缺来源和 busy/只读。兼容性以对应自动化路线与回归用例验证，详见 U7 报告。
- [x] 相关测试分组均记录退出码；未把分组结果描述成单进程全量通过。遵守本机运行条件，没有开展无关底层排查。
- [x] 用户另行要求打包后按 U8 全量重建，不只替换资源；audit_v1_bundle 检查 reaction_builder、reaction_builder_state、reaction_canvas、reaction_stage_inspector、workflow_state、project_actions、builder_drafts 等所需模块。EXE 默认界面实际点击搭建/改名，Agg PNG/SVG/PDF 通过；WebEngine 在源码与冻结版均报告 `profile.html failed to load`，详见 U8 报告。记录 EXE/ZIP 哈希和源码/包资源一致性。
- [x] 更新 docs/ux-v2-validation.zh-CN.md、AI_HANDOFF.md、docs/handoff.md 与 U7 验收报告；逐阶段记录实现、测试、桌面/包限制。

通过标准：用户拿到交付包后确实看得见并能使用新入口，不再依靠源码中存在某个类证明产品完成。

### U8：Windows 2.0.0 发行包与 EXE 验收

文件：`tools/build_windows.py`、`packaging/windows.spec`、`tools/audit_v1_bundle.py`、冻结版检查脚本和 U8 验收文档。

- [x] 版本元数据统一为 2.0.0；全量重建 Windows x64 onedir 便携包。
- [x] 审计 PE 固定/字符串版本、清单、ZIP CRC/布局、EXE 哈希、源码与包内资源 SHA，以及 U7 新增模块；10/10 检查通过。
- [x] 从冻结版默认首页实际点击新建、保存、项目名改名和“编辑反应路径”；改名后项目 UUID 不变，构建器可见。
- [x] 验证冻结 Agg 的 PNG/SVG/PDF 输出，均成功。WebEngine 源码及冻结版页面烟测均失败（`profile.html failed to load`）；保留为本机未通过项，不归因于打包本身，也不宣称 WebEngine/3D 通过。
- [x] 记录包/EXE SHA、截图、报告、运行环境和限制，更新总览与交接。

验收记录：[`docs/ux-v2-u8-validation.zh-CN.md`](ux-v2-u8-validation.zh-CN.md)。

## 10. 验收矩阵与可用性指标

| 编号 | 从哪里开始 | 操作 | 必须观察到 |
|---|---|---|---|
| A01 | 默认能量页 | 点“编辑反应路径” | 一次点击开当前路径，不需设置/右键/节点先加星 |
| A02 | WebEngine 失败 | 点同一原生入口 | 可打开搭建器，网页失败原因仍可见 |
| A03 | 任意页面 | 点项目名 → 重命名 | 最多两次点击到输入框；原名预填；取消不改数据 |
| A04 | 未保存项目 | 改名后首次保存失败 | 名称、草稿仍在，状态“保存失败”，可重试 |
| A05 | 有普通导入节点 | 打开搭建器 | 显示现有节点概览及转换说明，不无故空白 |
| A06 | 专家 AST 路径 | 打开/取消/另建路径 | 原 AST、参考和路径未被覆盖 |
| A07 | 基础搭建 | A+B → TS → C+D | 卡片、计量/能量项、连线与结果可逐项核对 |
| A08 | 同一阶段 | 改零点为产物 | 绝对值不变，纵坐标统一平移；局部差定义清楚 |
| A09 | 编辑草稿 | 关闭/恢复 | 有选择，无误丢；过期草稿不自动应用 |
| A10 | 应用并保存 | 取消文件选择后重试 | 不重复节点/路径，已应用状态与写盘状态分明 |
| A11 | 来源失效/无热校正 | 计算预览 | 显式诊断、可定位、不回退旧值或填零 |
| A12 | 分支/回汇 | 建边、拖位置、删边再撤销 | 拓扑正确；布局不改变能量；错误边可解释 |
| A13 | 只用键盘 | 搜索物质、加阶段、连接、检查、保存 | 功能等价，有可见焦点；不需拖拽 |
| A14 | 两路径含同物质 | 加星、保存、新进程重开 | 物质星标一致，路径/节点/物质身份不串线 |
| A15 | 交付 EXE | 从默认主图开编辑器并改项目名 | 与源码一致；记录实际 EXE 路径、SHA、DPR |
| A16 | 两路径共享同一节点 | 转换/编辑其中一条 | 明示共享关系，不能无提示修改另一条；原位身份策略拒绝共享节点，另建独立路径可继续 |

可用性目标：核心入口无需记忆二级“设置”菜单；搭建器里的问题项一次点击定位；拖动均有等价按钮；主按钮在最小窗口内可见。首次完整路径可以有必要的化学/来源确认，不通过取消科学确认项追求虚假的少点击指标。

性能目标只作本项目测量口径：本地选择/落区反馈优先在 100 ms 内；10 阶段常见草稿编辑不应长期阻塞主线程；耗时后台操作在 500 ms 内显示忙碌文字。记录本机样本、阶段数量、主线程延迟和 p95；不能把一次截图或空闲流畅写成性能通过。

## 11. 验证命令与报告格式

各阶段新增测试文件实际创建后再运行，不能复制本文计划命令冒充结果。沿用项目已有 Windows 兼容运行器，例如：

~~~powershell
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests/test_workflow_actions.py tests/test_project_management_ux.py -q
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests/test_builder_legacy_adapter.py tests/test_reaction_canvas.py -q
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests/test_builder_save_flow.py tests/test_builder_drafts.py -q
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests/test_reaction_network.py tests/test_multi_paths.py tests/test_s8_flow.py -q
.venv\Scripts\python.exe tools\check_ux_v2.py
~~~

桌面脚本使用独立 artifacts/ux-v2/runs/<uuid> 项目与偏好，保留原用户项目。截图在网页完成目标 project/revision/render_id 后再核对实际 DOM/可见窗口，防止截到旧帧。只允许把具备相应证据的验证项标通过；有测试失败先定位，不删除断言来获得绿色结果。

每阶段报告固定写：用户现在能完成什么、修改文件与接口、测试命令和退出码、实际桌面路径/截图、仍存在的限制、下一阶段前置条件。历史失败记录保留日期，不用“最新”反复覆盖而缺版本。

## 12. 风险、审查重点与停止边界

重点审查五类容易遗漏的输入：复杂旧 AST 转换、同名/多作业来源、真实零值与缺值、保存失败后的重复操作、过期回调/草稿。分别由 U3、U3/U5、U5、U2/U5、U5/U6 的具名用例负责。

允许 Luna 自行完成：显隐/菜单/QAction、路由兼容、Qt 卡片画布、详情表单、结构化提示、已有接口封装、受控转换、保存状态机、草稿文件保护、相关测试与交接。禁止通过文件名猜来源/角色、把画布位置写成能量、删掉科学核对、跨作业拼 Gibbs、重写 SQLite schema 或在 JS 中求值。

遇到下面具体边界时，先完成不依赖它的独立工作，报告复现与最小接口方案后停止相关阶段：

- 无法无损表达旧专家 AST：按第 4.5 节走保留/另建路线；不强行转译。
- 既有 SessionBackend 无法安全关联预览/保存完成结果：先实现 token 接口，不能依赖忙碌结束猜结果。
- 为实现基本入口/画布发现必须改变科学计算语义或 SQLite schema：写出必要性与替代方案，请求专项复核。
- 原生进程崩溃导致某验收无法稳定复现：保留日志和最后动作，区分产品断言与环境失败，不宣称通过；未受影响的文档/静态/单元任务继续推进。

本次目标达成的依据是“用户从默认界面完成实际路线”，不是控件对象存在、测试里直接构造窗口，或旧发行报告的通过数字。

## 13. 交给 Luna 的任务消息

> U0–U8 已完成。U8 发行包、EXE 验收、报告及 WebEngine 限制见 `docs/ux-v2-u8-validation.zh-CN.md`；总览见 `docs/ux-v2-validation.zh-CN.md`。包为 GaussianReaderPro 2.0.0 Windows x64 portable，哈希与产物路径记录在 U8 报告。不要把历史 L4/S8 报告当作 UX v2 验收；保持本文的科学与存储边界。若继续工作，先依据用户指定的新阶段，不要自行扩展。

