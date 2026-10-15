# S4 界面骨架与真实流程验收

完成日期：2026-10-15。范围：现代 Qt 工作台与真实 core/storage 服务集成，贯通导入、逐文件节点、参考/单位、计算、来源核查、保存和恢复。

## 交付

| 文件 | 作用 |
|---|---|
| src/gaussianreadpro/__main__.py / tools/run_app.py | 当前工作台入口、隔离测试配置参数、最近项目启动恢复 |
| services/session.py | 串行后台用例、导入合并、会话/仓库/恢复生命周期、重连与另存 |
| services/controller.py | Qt worker 调度、上下文守卫、取消、轻量模型编辑和工作状态合并 |
| ui/theme.py | 统一浅色字号、间距、卡片、色彩和控件设计 |
| ui/main_window.py | 首页/来源/路径导航、工具栏、属性证据、保存与关闭反馈、响应布局 |
| ui/tables.py | 基于 UUID 的模型/代理，数值、状态、筛选和独立视图排序 |
| ui/profile_preview.py | 当前核心结果的二维能级预览、悬浮和实际点选联动 |
| tests/test_workbench.py | 23 项用例/Qt 风险检查 |
| tools/check_s4.py | 原生桌面按钮/图形点选、保存重开和截图流程 |

没有新增依赖。保留原脚本、S0 prototype 和全部 S1–S3 核心/SQLite 契约；UI 不重写求值和参考扣减。

## 运行

```powershell
.\.venv\Scripts\python.exe tools\run_app.py
.\.venv\Scripts\python.exe tools\run_app.py "D:\Research\study.grproj"
```

也支持 python -m gaussianreadpro。项目安装后控制台入口为 gaussianreadpro；旧 gaussianreadpro-s0 入口保留。--preferences 和 --recovery-directory 可指定独立测试配置；正常运行使用系统应用目录与 QSettings。

导入文件后打开“反应路径”，选择能量类型，选中一个体系节点并点击“将此节点设为参考”。相对能量来自 calculate_path，只有所需来源/作业/字段均有效才给数值。默认 Gibbs 模式下单点 SCF 日志会显示 Gibbs 不可用，可切换 SCF；切换不会替换初次绑定作业。

支持本地文件和文件夹拖入、显式递归、重复路径跳过、搜索/状态筛选、表头排序与调宽、顺序上移下移、标签/角色编辑、参考设置、单位切换、来源 SHA256 重连和最近项目。排序通过代理改变显示，路径条目顺序只由明确顺序操作改变。

Ctrl+N/O/S/Shift+S 对应新建/打开/保存/另存为。保存和退出等待在后台执行，主窗口不会因等待 SQLite/哈希/解析而阻塞。只读项目禁用语义编辑，可以查看或另存。主文件保存与恢复副本状态分别反馈，首次未命名工作也有自动恢复文件。

## 测试证据

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe tools\check_s4.py
```

全量 **217 passed in 47.07s**，保留之前 194 项，新增 23 项 S4 检查。常规 Qt 测试用 offscreen 平台，实际桌面验收单独运行，报告 desktop_platform=windows。

关键风险检查：

- 同名不同路径导入分配不同 UUID/别名；重复路径跳过；文件夹递归显式选择；整批取消不合入新来源/节点。
- 实际点击参考按钮得到 ΔE=[0,.024,-.008,-.025] Hartree，kJ 换算与来源行号正确；实际点击能级点更新表格及 inspector。
- SCF-only 正常日志可导入和绑定，Gibbs 保持 unavailable；切换 SCF 后同一绑定可以计算。
- 表格排序、筛选后按 UUID 选择/移动仍正确，路径序列与视图排序分离；页面、筛选、选择、列宽、排序和分栏可保存。
- 解析 worker 人为等待时，GUI 5 ms 定时器在 75 ms 检查区间仍触发多次；取消可操作。这是事件循环响应检查，不是超大文件性能基准。
- 旧 revision 任务完成不能覆盖当前项目；打开不存在项目保留原表格/会话和就地错误。
- 删除外部源日志后，当前节点数值为 —，概览不画无效值，不越过缺失节点连接；原解析行号/快照仍保留。
- 保存失败不前进主库 revision，不显示已保存；重试成功清除错误。失败会阻止切换项目，避免关闭旧会话后丢工作。
- 只读主库不参与写回，直接关闭不弹保存失败；另存后可编辑且原库不变。
- 导入期间关闭先取消再 drain；退出保存失败可取消关闭、保留活窗口，重试后才真正关闭。只有已确认最新恢复成功才提供保留恢复退出选项。
- 非法旧显示提示回退，科研数据不丢失。恢复选择显式处理较新副本，未自动覆盖主项目。

## Windows 桌面与截图

tools/check_s4.py 用独立运行目录生成标明 SYNTHETIC 的 R/TS1/I1/P 日志，经 UI 导入和实际按钮设参考，核对人工值；设置 TS 角色并通过真实鼠标点选概览，然后保存、关闭，创建新 controller/window 打开同一库，核查精确项目/筛选/选择/结果。另导入固定 cclib G16 dvb_ir/dvb_sp/dvb_gopt，切换 SCF 并计算成功。

artifacts/s4/validation.json：passed=true、七项 checks=true、errors=[]，含本次可打开的项目路径、真实 SCF 结果明细与截图路径。一次完整脚本约 29.9 秒（同机并发运行回归），记录 2368 次心跳；包含多次窗口/项目、截图等待和原始日志读取，不作为生产耗时承诺。

已逐张查看宽/窄/首页截图，确认数值/文字可见、单位和参考清楚。窄窗口检查后降低了表格/预览最小高度，并让首页可滚动，避免底部说明被裁切。表格较矮时可正常滚动所有行。

| 截图 | 内容 |
|---|---|
| artifacts/s4/workbench-wide.png | 1500×950 逻辑尺寸，完整节点/能级概览/属性证据 |
| artifacts/s4/workbench-compact.png | 960×750 逻辑尺寸，导航简化、属性收起、图表保持完整 |
| artifacts/s4/sources.png | 来源表和作业/原值/行号/SHA256 证据 |
| artifacts/s4/home.png | 首次项目首页与空状态 |

本机 Windows DPI 缩放使 PNG 像素大于逻辑尺寸；未把截图像素误当窗口尺寸。

## 后续边界

S4 交付一条真实可用的科研工作流程。当前表达式/无效草稿可显示和存储，inspector 只编辑标签与角色；可切换已有多路径。S6 将接入组合/专家构建、完整节点/路径管理、批量编辑和撤销。S5 先把现有中文标签/诊断抽取成稳定键，完成 CN/EN 和主题/常规交互；当前语言偏好保存不表示界面已经能运行时切换。

二维概览是 S4 原生展示，不是最终 Plotly/PlotSpec 或 3D。S7 实现完整交互、视口、路径比较和正式导出；S0 离线 Plotly 的验证仍可复用，但固定样本不用于新工作台。失败文件重试和完整作业选择交互将在常规交互/编辑器阶段补齐；未识别来源始终保留证据、不补 0。

当前仅 Windows 桌面验证；macOS/Linux、超大批量性能、最终三平台打包分别留给 S8/S9。S0 frozen 包未重建，不能把旧原型发行包当成当前工作台成品。
