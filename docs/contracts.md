# 数据与接口契约 v1.8（S7 + EP 展示更新）

状态：S7 接入共享 PlotSpec、离线二维/三维、视图恢复与审计导出。S1–S6 科学、表达式与存储契约继续复用，SQLite 仍为 v1。S7 决定见 D033–D037，EP 展示更新见 D038。下文 S0/S4 原型描述为阶段历史，正式图表以此处协议 2 和 D038 为准。

## S7 图表、视图事件与导出

`build_plot_spec(project, results)` 从相同 project_id/revision 的当前 PathResult/NodeResult 构造不可变 PlotSpec/PlotPath/PlotPoint，按 PathEntry 顺序保存身份、Hartree、三个单位投影、公式/草稿、节点/参考依赖、作业/行号/SHA、诊断与常数版本。SessionBackend.view 在 worker 核查来源并计算后附带 SessionView.plot_spec。无效点保留身份但 value=null、valid=false，不使用零或最后有效值。

`plot_payload` 为 Plotly、Matplotlib 和 HTML 提供相同坐标、顺序、单位、标签偏移/格式、配色和参考。比较仅纳入同类型/模式并使用活动路径单位；不同参考警告且禁用跨路径差值，不自动改零点。参考签名忽略 AST 位置，保留 UUID/AST/用途/组合模式和草稿；不证明代数等价。`compare_points` 在 Python 先求 Hartree 差再转换；局部势垒必须同路径、第二点为明确 TS、第一点为相邻前驱，且显式点击标注。

生产页面 profile.html/profile.js 本地加载 vendor/plotly.min.js，通过 QWebChannel 协议 2 握手。每次显示投影递增 render_id，语言/主题改变也不例外。事件携 type、project_id、revision、render_id 和现存 path/entry/node ID；检查当前上下文、64KiB 上限、白名单。旧事件、非法身份和科学值写入忽略。Plotly.react 串行合并更新，监听器单次绑定。JS 不求值、不转换科学值、不拟合峰谷，不执行用户文本。标签转义，禁止远程连接/导航；本地信任的 Plotly WebGL 脚本保留其所需能力。

二维 x=步骤、y=当前模式能量；三维 x=步骤、y=路径类别、z=同值。按用户指定 demo（D038）默认使用平滑高光曲线、圆形节点、橙色选中光晕和三维装饰光带，替代能级横杠。`paths[].curve_runs` 是纯显示采样：相邻有效端点之间 smoothstep、经过端点且不超出端点范围，缺值严格分段；三维装饰幕和光带只沿单一路径绘制，禁用 hover/选点，不能作为势能面、置信区间或新科学值。计算、势垒、CSV、来源、hover 和节点身份仍只读取 `points`。协议仍为 2，SQLite 仍为 v1。二维只允许标签文本像素偏移。WebGL 失效说明并降级二维，页面失败回原生预览；只读项目视图仅当前会话有效。

S7 plot_state 键：mode=2d|3d、compare=bool、theme=auto|light|dark、hidden_paths=[path UUID]、label_offsets={entry UUID:[dx,dy]}、viewports={context:{x_range?,y_range?,camera?}}、barrier=null|{path_id,from_entry,to_entry,offset?}。context 为 project/path/unit/kind/mode/2d或3d。范围有序有限，相机和偏移限幅，bool 不能冒充数值；其他已有阶段字段保留。约 400ms 与工作区合并新修订，再进入 S3 自动保存。图表主题属于项目视图；应用语言/主题仍为本机偏好，忙碌时合并最新请求排队。

导出前检查项目/revision，worker 重新核对来源 SHA 并计算，不能将未连接历史值作为当前有效值导出。只创建不存在的新目录；在私有暂存区完成后复制发布以继承目标权限，失败清理，拒绝覆盖已有目标。每包包含 profile.扩展名、data.csv、sources.csv、plot.json、manifest.json（哈希/大小/渲染元信息）；HTML 带 assets。CSV utf-8-sig，文本公式注入加单引号保护；JSON 原文保留。附 UUID、表达式、参考、源路径、作业/行号和 SHA。

二维 PNG/SVG/PDF 默认白底，由后台启动纯 Matplotlib Agg helper，入口 `--render-static request destination` 必须在 Qt 导入前分派，120秒超时，冻结包须保留。三维仅 PNG/HTML；PNG 核对当前 render_id 后捕获，验证 PNG/1600×1000/体积，不承诺纯矢量。捕获暂缓视图保存以稳定修订，完成后恢复。导出语言独立选择。HTML 整目录可离开 Qt 离线使用，保留浏览器内视口/相机/标签，但不回写项目。

S5 纯展示层使用 `resources/locales/zh_CN.json` 与 `en_US.json`，键集合必须一致。语言、主题在 LocalPreferences 中即时保存，不写入 Project、SQLite schema 或 revision。首次语言偏好为 `system`，界面按系统 locale 选择中文或英文，用户手动切换后保存明确语言。切换语言保留项目数据、计算值、筛选、排序、选择和分栏；文件名、项目名、用户标签、表达式与 UUID 不翻译。翻译缺项回退源文案。主题只替换 UI tokens，不触发计算或项目编辑。`system` 主题按 Qt color scheme/系统调色板选择浅/深方案。

## 身份、数值与语言

S6 UI 契约：`ui.expression_editor.ExpressionDialog` 同时编辑 node_id 或 path_id，所有组分调用 `components_expression`，专家文本调用 `edit_expression`；组合模板调用 `composite_gibbs_expression`。不在 UI 重算能量，预览从 SessionBackend 返回的当前来源有效性覆盖及 `calculate_path` 获取。输入停止约 350ms 后保存表达式/无效草稿；正在执行上一修订时继续接收输入，最新草稿等待串行提交，关闭编辑器会排空待提交项。

`services.expression_editor.component_form` 只识别无需分配、合并常量或舍入系数的简单线性组分；其他表达式保持专家模式，禁止静默重写。构建器最多 40 行；spinbox 不能精确承载的已有数字也保留专家模式。新节点从可保存的空草稿开始，零偏移仅在用户提交显式组分操作后生成。

工作区可增加 `expression_editor={target,mode,text,rows,offset,unit}`；rows 保存 source/job/kind/coefficient/source_text，用于恢复未完成的选择。它不是求值输入，只有对应文档仍为同一无效草稿时才恢复；科学 AST 与 draft_error 始终决定结果有效性。Qt UTF-16 光标位置与核心 Python 字符位置在 UI 边界转换。

`ProjectController` 提供 set_expression、add_node/remove_nodes、edit_path、apply_change、preview_change 和 undo/redo。撤销最多保留 100 个会话快照；撤销/重做仍产生 current_revision+1。打开/新建/恢复、导入和重连清空历史，不能通过撤销恢复过期解析。视图状态沿用当前值，公式选择草稿提示跟随相关历史恢复；历史不跨重启存储。复制路径生成新的 path/entry UUID 并共享 node UUID；从路径移除节点只删除不再被其他路径使用的所选节点，参考表达式是独立快照。

批量编辑以稳定 ID 选择，先在 worker 核查当前来源并生成预览，预览的待选修订不写入恢复/主项目；只有用户应用才调用 ProjectChange.apply，旧 base_revision 拒绝。支持添加组分、精确替换引用、复制表达式模板和跨路径统一参考。删除来源先展示 `find_source_usage` 的节点/参考路径依赖，引用存在时仅在明确级联选择后删除；可撤销，重新计算仍核查当前来源。

- 持久化 ID 为小写 UUID 字符串；创建后不可变。路径、文件名、别名和表格行号均不是身份。
- 枚举使用固定英文值；界面按语言映射。用户标签/原文件名不翻译。
- 来源能量用有限 Python float/Hartree 计算；保留原始数值字符串用于核对。显示舍入不回写原数据。JSON 禁止 NaN/Infinity。
- 未识别或缺失数据为 null，绝不能使用 0。已识别的元数据值与未识别状态分开。
- 诊断包含 `code`、`severity=info|warning|error`、`params`、`source_line?`。不以中文消息字符串决定流程。

## 模型

| 对象 | 必须字段 |
|---|---|
| SourceFile | id, original_name, display_name, original_path, relative_path?, size_bytes, mtime_ns, sha256?, parser_version?, import_state, jobs[] |
| JobRecord | id, source_file_id, ordinal（从 0 开始）, start_line, end_line, termination, scf_convergence, metadata, energies, diagnostics[] |
| EnergyValue | kind, value_hartree, raw_text, source_line, job_id |
| EnergyRef | source_file_id, job_id, kind_policy, kind? |
| ExpressionDocument | format_version=1, ast, display_text, purpose, combination_mode, draft_text?, draft_error? |
| ProfileNode | id, label, role, expression, display（含标签偏移） |
| PathEntry | id, node_id, position（从 0 开始） |
| ReactionPath | id, label, entries[], energy_kind, reference_expression?, calculation_mode, unit, color, visible |
| NodeResult | entry_id, node_id, absolute_hartree?, reference_hartree?, relative_hartree?, display_value?, unit, dependencies[], diagnostics[], valid, revision |
| Project | id, schema_version, revision, unit_constants_version, source_files[], nodes[], paths[], alias_bindings, plot_state, workspace_state |

S1 模型为 frozen dataclass，映射和诊断参数递归冻结；通过 `snapshot_to_dict()` 输出 JSON 兼容投影。SourceFile 无法读取时 size_bytes/mtime_ns 为 null；失败、取消或读中变更时 sha256 为 null。SourceFile 的 id 默认新建，调用方必须传入并保存已有文件 UUID，不能依赖文件名反推身份。

JobMetadata 包含 route、method、basis_set、scf_method_label、temperature_kelvin、pressure_atm、charge、multiplicity、solvent、source_lines；未识别字段为 null。S2 已补充 ProfileNode、PathEntry、ReactionPath、Project 和结果对象。Project.alias_bindings 为只读 alias→EnergyRef 映射，必须与草稿一起保存，不能按当前表格顺序重新猜别名。悬空来源引用可保存但计算返回错误；路径指向不存在节点或重复身份则拒绝构造。

一个节点可供多个路径引用；路径顺序属于 PathEntry，不能存到文件或节点上。同一节点在不同路径采用不同参考时，结果由 entry_id/path_id 定位。标签偏移等与具体路径相关的覆盖可放入 PathEntry.display_override，节点保留默认显示。

SourceFile.import_state：`pending|reading|ready|partial|failed|cancelled|stale|missing`。JobRecord.termination：`normal|error|incomplete|unknown`。SCF 收敛：`converged|failed|unknown`。缺字段和作业异常结束分别是诊断；不得由字段缺失直接推断 SCF failed。

Energy kind：`scf|gibbs_correction|gibbs_total`；Unit：`hartree|kcal_mol|kj_mol`。Role：`reactant|intermediate|transition_state|product|unspecified`。kind_policy：`fixed|follow_path`；fixed 必须有 kind，follow_path 禁止额外 kind。

## 日志选择与来源规则

1. 逐作业保留字段。同一作业中同一能量类型最后一次出现的有效数值胜出，并保留其行号。
2. 不把前一个作业的 Gibbs 字段与后一个作业的 SCF 混合。作业边界需要真实 Gaussian 样本校准；合成 fixture 中边界显式标注，不代表所有真实输出格式。
3. 默认选择“最后正常结束且有当前能量类型的作业”；若存在更晚失败/未结束作业，返回诊断 `later_job_not_normal`。
4. 若无正常候选，不悄悄选择失败作业。允许用户显式选取，返回终止状态警告。无候选为 unavailable。
5. 单点 SCF 正常结束是 ready；只针对所需字段给出可用性。错误日志中存在能量可记录，但不能宣称该计算正常成功。
6. 数字接受正负号、小数和 E/e/D/d 指数；读取行号从 1 开始。原始日志使用分块/流式读取。
7. 自动选择仅用于首次绑定或用户显式执行重新选择；已绑定 EnergyRef.job_id 后切换能量类型，缺字段应返回 unavailable，不自动跳到另一个作业。界面显示各数值来源，不能将按类型挑出的不同作业值表现为一个完整作业结果。
8. 作业在正常/错误终止行结束；运行时 `Link1: Proceeding to internal job step number …` 或新的 `Entering Gaussian System` 建立下一作业。普通 `Entering Link 1 = …` 不切分已有作业；原始输入中的 `--Link1--` 不作为运行时证据。缺终止记录时按 incomplete 处理。
9. job_id 使用文件 UUID 为 namespace，结合 parser_version、起始行和完整作业内容摘要生成 UUID5。原始作业字节/起始行不变时 ID 可保持；内容或位置变化时 ID 改变，需要明确重绑，不能按 ordinal 静默复用。
10. cancelled/failed/missing/stale 源快照不用于新的计算；部分日志仍可按正常候选策略使用已确认正常的作业。显式选择失败/未结束作业保留警告。读取过程中前后 size/mtime/inode 或读取大小变化时标记 stale。

已实现的 S1 接口：

```python
parse_log(path: Path | str, source_file_id: str | UUID | None = None,
          cancel: Callable[[], bool] | None = None,
          *, max_line_bytes: int = 65536, read_chunk_bytes: int = 65536) -> ParseResult
select_job(source: SourceFile, kind: EnergyKind | str,
           policy: SelectionPolicy = SelectionPolicy.LAST_NORMAL_WITH_ENERGY,
           *, job_id: str | UUID | None = None) -> JobSelection
from_hartree(value: float, unit: Unit | str) -> float
to_hartree(value: float, unit: Unit | str) -> float
convert_energy(value: float, source_unit: Unit | str, target_unit: Unit | str) -> float
```

ParseResult 包含 source、文件级 diagnostics、lines_read、bytes_read；各作业诊断位于 JobRecord.diagnostics。JobSelection 包含 job、energy、diagnostics、available 属性。job_id 显式选择严格定位，不回退。未知 kind/policy/UUID 属于调用参数错误，抛 ValueError；文件读取和取消作为结构化结果。默认采用 UTF-8（首行接受 BOM），无法解码时保留替换字符并给诊断。单行/路线/诊断数量有上限，避免异常输入耗尽内存或冻结；取消按读取分块检查。

S2 已实现接口（纯 Python）：

```python
compile_expression(text, aliases=None, *, purpose=ExpressionPurpose.SYSTEM,
                   combination_mode=CombinationMode.STANDARD) -> CompileResult
evaluate_expression(expr: ExpressionDocument, context: EnergyContext) -> ExpressionResult
calculate_path(project: Project, path_id, *, allow_abnormal_jobs=False) -> PathResult
edit_expression(current, text, aliases=None, *, purpose=None, combination_mode=None) -> ExpressionDocument
render_expression(expression, aliases=None) -> str
components_expression(components, *, offset=0, offset_unit="hartree", aliases=None, purpose=...) -> ExpressionDocument
composite_gibbs_expression(high_scf_ref, low_gibbs_ref, low_scf_ref, aliases=None) -> ExpressionDocument
```

所有接口不导入 Qt。解析中的文件读取异常必须返回/抛出有明确 code 的失败，不能只 print 后返回全 null。

## 表达式协议

语义树的每个节点都有 `type`：

```json
{"type":"ref","source_file_id":"uuid","job_id":"uuid","kind_policy":"follow_path"}
{"type":"scalar","value":0.5}
{"type":"energy_constant","value":1.0,"unit":"kcal_mol"}
{"type":"unary","op":"neg","operand":{"type":"ref","source_file_id":"uuid","job_id":"uuid","kind_policy":"follow_path"}}
{"type":"binary","op":"add","left":{},"right":{}}
```

add/sub：左右维度相同；mul：至少一侧为 scalar；div：分母必须 scalar 且非零。最终表达式维度必须 energy。允许括号与 unary +/-。不支持调用、属性访问、索引、幂或对节点的引用。

文本入口以 `@{alias}` 表示源引用，别名唯一、可补全；插入后解析为 UUID。文件名包含 `}` 时使用独立安全别名，不把文件名直接作为语法 token。AST 是唯一求值依据；编译入口的 display_text 保留原始文本，render_expression 按当前别名重建展示。改名不改 UUID；draft_text 原样保存并重新校验。

建议限制：文本长度 8192 字符、树节点 256、深度 32。拒绝 bool、非有限数值和数值溢出。不使用 eval/exec。限值是可调整配置，但变更应有异常输入验证。

calculation_mode：

- `relative`：各节点 expression 是体系绝对能量；最终只减一次 reference_expression。reference 不能为空。
- `absolute`：无参考，展示体系绝对能量。
- `direct_difference`：节点 expression 本身为能量差；reference 必须为空；不生成可误解的绝对能量字段。

普通路径下，不允许把直接差值表达式与绝对体系节点混在一起。无效草稿使该节点当前结果 invalid；历史有效值如继续展示，必须标记 stale，不参与导出。

## 图表协议 v1

Python 向 JavaScript 发送有限数值的 JSON：

```json
{
  "protocol_version": 1,
  "project_id": "uuid",
  "revision": 1,
  "view": "2d",
  "unit": "kcal_mol",
  "energy_label": "Relative Gibbs energy",
  "reference_label": "R + A",
  "points": [
    {"node_id":"uuid","entry_id":"uuid","label":"TS1","x":1,"value":15.06,"role":"transition_state"}
  ]
}
```

生产版本加入 paths、诊断和标签偏移。S0 仅用一个固定合成路径验证载入、渲染和事件链路，不作为最终 PlotSpec 实现。

握手：JS `bridge.pageReady(protocol_version, plotly_version)`；Python 检查协议后发 dataChanged(JSON)。渲染后 JS 回传 `rendered(revision, summary_json)`。点击回传 `pointSelected(node_id, revision)`，Python 校验 ID 和 revision。错误通过 pageError 回传；超时也算失败。

不发可执行代码，不把用户标签拼入 HTML/JavaScript。图表更新用 Plotly.react；使用 uirevision 保持视口。来自旧 project/revision 的事件被丢弃。

## 项目存储协议

生产格式：扩展名 `.grproj`，SQLite；schema_version=1，PRAGMA user_version=1，application_id=0x47525052。表结构已在 S3 固定：metadata、source_files、jobs、energies、nodes、paths、path_entries、workspace_state；复合值使用严格 JSON 字段。

- 单一执行器拥有连接；事务成功后才更新 saved_revision。
- 每次模型变更 revision+1；保存快照保证跨表一致。UI 临时进度不触发科研数据 revision。
- 先检查 schema；迁移前 backup；失败回滚；更高版本不得写入。
- 来源保存相对路径和 fingerprint；重新定位按 fingerprint 核实；缺失时保留解析快照。
- 来源重解析后 job_id 的保留只能基于明确匹配；无法确定对应关系时提示引用需重绑，不能按 ordinal 静默指向新作业。
- 项目锁避免同时写；另存为采用 SQLite backup API。
- 语言、最近项目和默认目录属于本机 QSettings；项目保存当前工作区、图表相机和公式草稿。

## 单位与可核对示例

S0 基准沿用旧脚本舍入常数 `HARTREE_TO_KCAL=627.509474063`、`HARTREE_TO_KJ=2625.4996394799`，继续用于 S0 原型和其人工 oracle。

S1 已核查来源，采用 `CONSTANTS_VERSION=codata_2022_thermochemical_calorie_v1`：Hartree 为 `4.3597447222060e-18 J`、Avogadro 为 `6.02214076e23 mol^-1`；热化学 kcal 为 `4184 J`。用 Decimal 推导后转 float：1 Hartree ≈ `2625.499639479163 kJ/mol` ≈ `627.5094740628975 kcal/mol`。来源：[NIST CODATA 2022](https://physics.nist.gov/cuu/Constants/Table/allascii.txt)、[NIST 热化学卡路里定义](https://www.nist.gov/pml/special-publication-811/nist-guide-si-footnotes)。Hartree 常数存在测量不确定度，推导的小数位不代表物理精度承诺；数值舍入只在显示层进行。S3 项目应保存换算常数版本以便复现。

合成 R=-150.0、TS1=-149.976、I1=-150.008、P=-150.025 Hartree；参考 R。预期 ΔE：[0, 0.024, -0.008, -0.025] Hartree。kcal/mol：[0, 15.060227377512, -5.020075792504, -15.687736851575]。基准用十进制精确值计算，生产 float 测试采用合理容差。

## S2 实施细则

**语法与安全。** 独立 tokenizer/Pratt parser，不调用 Python eval/exec。示例：`@{TS1} - (@{R} + @{A}) + 1[kcal/mol]`。无单位数字只作系数；偏移量显式写 `[hartree]`、`[kcal/mol]`、`[kJ/mol]`，也接受内部单位字符串。E/D 指数受支持；`0[hartree]` 是有效零参考。文本 8192 字符、语义树 256 节点/深度 32 和 tokenizer 数量上限已启用；直接构造树也验证 schema、数值、规范小写 UUID、维度和资源限额。

**别名。** AliasIndex.from_pairs 拒绝重复名；with_unique_labels 分配 `species (2)` 等唯一别名，为花括号名称等生成安全别名。精确、大小写敏感；相似名称只作建议。`ref:` 为保留前缀：`@{ref:文件UUID/作业UUID}` 表示跟随类型，追加 `/scf` 等后缀表示固定类型，可在没有别名索引时精确重建。Project.alias_bindings 保存用户命名空间；不从文件名模糊恢复引用。

**错误位置与草稿。** AST 可选 `span=[start,end]` 为编译原文字符偏移，程序组合/替换树时清除旧 span。无效草稿允许保存至 65536 字符，并使当前表达式不可计算，即便保留了最后有效 AST。CompileResult 提供 expression/diagnostics/valid；ExpressionResult 提供 value_hartree/dependencies/diagnostics/valid；错误、缺值返回 null。

**显式语义。** purpose 为 `system|difference`，编译时由调用方指定；不凭正负号猜测用户意图。combination_mode 为 `standard|composite_gibbs`。standard 的有效引用类型必须与路径类型一致；composite_gibbs 明确允许 SCF/Gibbs 总值组合，目标路径必须为 Gibbs 总能量，始终给近似警告。高低级别模板强制固定高层 SCF、同一低层作业的 G 和 SCF。自定义 composite_gibbs 表达式仍受同样维度检查，属于用户明确选择的近似组合。

**来源质量。** EnergyContext 绑定 UUID 索引与路径能量类型。非正常结束作业默认不可计算；显式 bool `allow_abnormal_jobs=True` 可在保留警告下使用已取得能量，明确 SCF 未收敛仍阻止计算。选定字段错误阻止计算，其他能量字段错误降为警告。缺失/失败/取消/stale 源不用于新计算。0×缺失引用也不能掩盖缺失数据。

**结果。** NodeResult 分别保存节点依赖与参考依赖的文件/作业/类型、行号、原值、SHA256 和元数据，包含 revision/valid。direct_difference 的 absolute/reference 为 null；absolute 的 relative 为 null。参考不可用时可保留有效节点绝对值供排查，但 display_value 为 null 且 valid=false。PathResult 带模式/类型/单位/转换版本；已知条件冲突为 warning，条件未知为 info，不视作已验证一致。

**批量修改。** project_edits 提供 add_component_to_nodes、replace_node_references、set_reference_for_paths、reorder_path、find_source_usage、remove_sources。修改返回 ProjectChange，原快照不变，新 revision=旧+1。calculate_preview 供检查，apply 校验项目和基准 revision。直接差值路径不能再附加参考；未知目标或无效草稿的批量公式修改整体失败。后续撤销控制器应让新 revision 单调增加。

**依赖删除。** 检查当前/保留 AST 与草稿中完整可解析引用 token，默认抛 ReferencedSourceError(usage)。显式 cascade 才移除相关节点/条目。参考依赖被删来源时，相关路径也列为移除，不隐式切换绝对模式；级联清理对应别名。

**S3 存储实现。** 保存 alias_bindings、表达式 purpose/combination_mode/AST/草稿、单位常数版本与所有稳定身份；加载时重建并校验 dataclass。snapshot_to_dict 是 JSON 投影，严格加载入口为 storage.codec.project_from_dict/decode_project；恢复不执行任意 Python 对象。

## S3 仓库与恢复接口

```python
ProjectRepository(path, *, create=False, read_only=False, timeout=.25,
                  backup_timeout=5., fault_injector=None)
repo.load() -> Project
repo.save(project) -> int  # committed revision
repo.backup_to(destination) -> Path  # exact snapshot, SQLite backup API
repo.save_as(destination) -> Path  # backup + verified source path rebasing
repo.close()

RecoveryService(recovery_path, *, repository=None, debounce_seconds=1.,
                recovery_fault_injector=None)
service.request(project)
service.flush() -> SaveStatus
service.status -> SaveStatus
service.close() -> SaveStatus
list_recoveries(directory) -> tuple[RecoveryCandidate, ...]
restore_session(repo) -> RestoredSession
inspect_sources(project, directory) -> tuple[SourceConnection, ...]
reconnect_source(project, source_id, path, directory) -> ProjectChange
reconnect_directory(project, directory, project_directory, *, max_files=10000) -> DirectoryReconnect
export_bundle(repo, destination, *, include_source_ids=()) -> Path
import_bundle(archive_path, destination, *, max_bytes=1073741824, max_files=10000) -> Path
```

**SQLite 布局。** metadata 保存 format、id、schema_version、revision、unit_constants_version、snapshot_digest。source_files/nodes/paths 保存 id、独立 position 和 JSON payload；source_files.payload 不内嵌 jobs。jobs 以 source_file_id/position 分组，payload 不内嵌 energies；energies 以 job_id/kind 为键。path_entries 按 path_id/position 保存 id 与节点引用，paths.payload 不内嵌 entries。workspace_state 的三行分别为 plot_state、workspace_state、alias_bindings。外键、唯一键、连续位置、行内身份与 payload 一致性、孤立行均检查；SHA256 为规范排序 JSON 快照摘要，用于意外损坏检测，不是认证签名。读全表也使用同一事务。

**类型检查。** 只接受模型定义的全部字段和类型，拒绝未知/缺失字段、bool 冒充数值、非规范 UUID、非法枚举/AST、非有限数值与重复 JSON 键。JSON 每段最多 64 MiB、嵌套 64 层；完整项目摘要序列化也受 64 MiB 上限，超限保存整体回滚。项目内允许无效草稿/缺参考/悬空能量引用，恢复后继续 invalid，不能删除这些未完成工作。没有 pickle 或自动执行协议。

**写入与并发。** 一个仓库拥有一个单线程执行器及一个线程专属 SQLite 连接；各数据库连接不跨线程。保存使用 BEGIN IMMEDIATE、DELETE journal、synchronous=FULL，跨表全部替换在一笔事务提交。saved_revision 仅在提交成功后前进。较低 revision 拒绝；相同 revision 仅允许完全相同快照的幂等保存；项目 ID 不可变；检测到外部修订冲突要求重新打开。初始化完成但还没首次保存的库可重新打开，load 返回 empty_project；不作为有内容的恢复副本。写锁使用持有期间的操作系统文件锁，崩溃自动释放，.lock 文件保留以避免 inode 竞争；第二实例退为只读。只读数据库拒绝 save，独立恢复副本仍可保存编辑。

**版本与备份。** 不相关 SQLite 数据库和更高版本拒绝打开/写入。v0 仅识别同 application_id、单 legacy_project(id=1,payload) 表，payload 为完整当前 Project JSON 的预发布迁移测试格式；不是已发布兼容承诺。先用 SQLite backup API 生成唯一 .pre-v1-UUID.bak，再在单事务内迁移 DDL+数据+user_version，失败保留原 schema/内容和备份。backup_to 和 save_as 先写临时文件再发布，拒绝已有目标；备份等待受 backup_timeout 限制。save_as 将可验证来源相对于新目录重建路径，路径变化时新副本 revision+1，原项目不变；没有可验证来源时保留原路径提示和离线状态。包导出以一致备份为起点。

**自动恢复。** request 按当前模型快照约 1 秒防抖，flush 手动同步、close 等待并补写最后请求；新请求在旧写入期间到达也不会丢失。恢复文件与主文件必须不同；同项目同修订不同内容拒绝；两个服务不能同时写同一恢复文件。恢复先保存，主项目后保存，二者不是跨数据库原子事务，分别报告成功修订。SaveStatus 含 current_revision、saved_revision、recovery_revision、pending、saving、error_code、recovery_error_code；失败保留 pending，等待显式 flush/新变更/close 重试，不持续空转。无主仓库时 saved_revision 始终 null。关闭返回错误仍意味着有未保存工作，UI 必须处理；服务不关闭调用方的主仓库。

**来源恢复。** SourceConnection.state 为 available/missing/changed/unverified/unreadable；先试相对路径，再试本机可识别的原绝对路径。完整 SHA256 流式核对，读前后 stat 一致才可用；无 SHA256 不能只凭同名或 mtime 自动确认。restore_session.snapshot 为精确保留的历史证据；calculation_project 是临时状态覆盖，不写回仓库，把未连接/变更来源标 missing/stale，曾 pending/reading 的来源也禁止恢复运行。历史计算可从 snapshot 重现，但 UI 必须标“历史/来源未连接”，不得当成当前有效结果导出。reconnect_source 只接受同指纹，保留文件/作业 UUID，返回一个新修订预览；目录扫描遇到多个同指纹候选列为 ambiguous，不静默任选。

**本机偏好和可移植包。** LocalPreferences 为惰性导入 Qt 的 QSettings 适配器；language=zh_CN|en、theme、recent_projects（最近优先、最多 20）、window_geometry、default_export_directory 独立于 Project。sync 非 NoError 抛 preferences_save_failed；不能据失败缓存显示保存成功。启动时由 UI 根据 last_project 和恢复候选选择，不自动覆盖。图表、选择、筛选、顺序和原样公式草稿属于项目快照。default_recovery_directory 需在配置 Qt 应用名称后调用。

.grpack 为 ZIP，根 project.grproj、manifest.json 和用户明确选择的 sources/文件UUID.log；默认不打包日志。manifest 精确为 format=gaussianreadpro.bundle、version=1、source_ids=[]，不允许重复 ID，最大 1 MiB。附件以 manifest 显式列举，不凭项目中的旧相对路径推断；成员与清单必须完全一致。包内路径变化增加一个修订；选定日志必须已验证且复制后再次核对 SHA256。导入先验证所有路径/体积并在临时目录解包，拒绝绝对路径、驱动器、反斜线、..、重复大小写名、符号链接、加密成员及不识别内容；再校验数据库和包内日志指纹，最后发布新目录。声明的包内日志缺失也拒绝。已有导入目录不覆盖；超限或任何失败不发布半成品。

**UI 线程边界。** 上述公共接口为同步接口；连接安全不代表调用不会等待。S4 须在后台任务调用解析、保存、恢复指纹、目录扫描、包传输和关闭；UI 仅在自身线程读取状态/处理完成信号。语言偏好可恢复尚不代表运行时 CN/EN 界面已实现（S5）。

## S4 工作台与会话

- 入口：gaussianreadpro.__main__:main，tools/run_app.py 或 python -m gaussianreadpro。Qt 应用名称为 GaussianReadPro，QSettings 与恢复目录使用 S3 适配器；可用 --preferences / --recovery-directory 隔离测试配置。启动完成 bootstrap 后，显式 CLI 项目优先，否则自动尝试最近项目；没有记录时显示首页，打开失败保留当前会话和就地错误。
- services.session.SessionBackend 只承载串行后台用例，持有主仓库/RecoveryService 生命周期；project_id/revision 和科学值仍属于 core。new/open/recover/update/import_files/save/reconnect/shutdown 返回不可变 SessionView 或 RecoveryOffer。SessionView 带 project、results、connections、path、read_only、status、message、recent_projects。
- services.controller.ProjectController 是主线程 QObject。单工作线程 QThreadPool(maxThreadCount=1, expiry=-1) 执行用例，存储仓库继续各自独占连接。任务 token 同时绑定项目 UUID/revision；旧任务/旧上下文结果不覆盖当前状态。主线程只做不可变轻量模型编辑与 UI 映射，计算/解析/来源哈希/偏好与项目 I/O/关闭都在后台。
- busy 时禁用项目变更和语义编辑，保留导入取消；正在进行的导入在文件间、目录扫描及 parse_log 的分块处检查 Event。取消是整批导入不合入新来源/节点/别名，原项目保持；已完成提交才收到的取消不撤销已完成工作。窗口关闭在导入期间先请求取消，再异步等待最终 flush。
- 初次导入按当前路径类型选择正常作业；Gibbs 不存在时可绑定正常 SCF 作业，Gibbs 仍不可用。只在导入时绑定一次具体 job_id，切换类型不借用其他作业。无法找到正常可绑定作业的日志仍保留在来源表，展示作业证据，不补 0。重复绝对路径跳过；不同目录同名分配独立 UUID 和唯一别名。目录默认不递归，用户显式勾选；本次候选上限 10000。
- QAbstractTableModel + QSortFilterProxyModel 投影来源与节点；UserRole 为 file_id/node_id，节点额外 role 定位 entry_id。排序/搜索只改变代理映射，路径顺序只经 reorder_path 更改。来源表从已绑定作业显示 SCF/Gibbs 原值；缺值为 —。结果和概览使用 calculation_snapshot 后的 calculate_path，不把历史来源快照当作当前有效计算。
- workspace_state 的 S4 规范键：page=0|1|2、path_id、node_id、source_id、filter、file_filter、horizontal_splitter/vertical_splitter（两个正整数）、source_widths/node_widths（前五列像素宽）、source_sort/node_sort（列号与 Qt 方向整数）、source_base_dir。未知字段保留；不适用或非法显示提示回退，不破坏科研快照。plot_state 保留既有字段，完整相机交互在 S7。workspace 更新约 400 ms 合并为新修订，再由 S3 约 1 秒防抖备份。
- 标签/角色、类型/单位/模式、设置参考、显式顺序变化增加 revision。新科学修订计算期间清除旧结果显示。当前 inspector 展示表达式/原样无效草稿，只编辑标签和角色；组合/专家公式编辑器在 S6，不在 UI 重写 DSL。读取多路径项目可切换既有路径；完整创建/复制与批量编辑在 S6 接入。
- 新会话使用 project_uuid-session_uuid.grproj 恢复文件，避免 Save As 分支或多实例同 UUID 的恢复锁冲突。发现命名项目存在较新恢复副本先返回 RecoveryOffer，UI 明确选择恢复/打开已保存项目/取消；未命名副本可从首页选择恢复。打开成功和保存成功更新最近项目。
- 只读主项目禁用语义编辑、保留查看与另存为；其 RecoveryService 不附只读主仓库，不无谓尝试写回主文件。另存为把当前模型与已核实来源路径写入暂存 SQLite，再以 backup API 发布新文件并切换会话；原文件不变，目标存在则拒绝覆盖。
- close 先提交工作状态，再在后台 flush/shutdown，成功后才接受 closeEvent。失败保留窗口及活会话，用户可重试/另存/取消；只有最新恢复副本已确认成功时才提供“保留恢复副本并退出”。saved_revision 和 recovery_revision 各自显示，失败不标“已保存”。
- ui.theme 为 S4 浅色设计 tokens；QSplitter 在窄窗口收起 inspector 和导航文字，属性按钮可重新打开；首页允许滚动以适配较低窗口。ProfilePreview 为原生二维预览，绘制真实能级与虚线引导、悬浮和点选；不跨越缺失节点连线，不计算势垒、不拟造曲线或势能面。S7 再实现共享 PlotSpec、离线 Plotly/3D、缩放视口和正式导出。
