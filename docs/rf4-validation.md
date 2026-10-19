# RF4 结构预览、详情、概览与关键能量表

2026-10-17：RF4 源码阶段完成。本轮先集中实现，最后集中运行交互/回归检查，只在验收末尾保存深浅色窗口图。未开始 RF5–RF8 或重建 EXE。

## 实现与边界

- `services/structure_preview.py`：独立展示解析器 `orientation-preview-v1`，不改变核心 Gaussian 解析版本、source/job UUID 或能量计算。只扫描指定 JobRecord 的起止行；优先最后一个完整且受支持的 Standard orientation，没有时回退 Input orientation。记录来源 SHA、job_id、方向类型、Angstrom 单位、坐标段行号。
- 每次读取（包括命中缓存）都重新核对完整 SHA 和读前/读后/路径 stat。串行 worker 读取，可取消；文件上限 64 MiB、原子上限 1000，缓存最多 32 组。未知单位、虚原子/非法原子序数、非有限坐标、未闭合表格不生成模型；缺失/变更/不可读来源显示明确状态。当前支持 Angstrom 表；Bohr 明确报不支持，不猜测单位。
- `ProjectController` 复用现有单线程 pool；最新结构请求在忙碌任务后合并处理，旧请求可取消，项目/修订与选点签名守卫拒绝过期结果。来源读取发现变化时重算当前来源状态，避免继续展示历史值。没有增加并行 SessionBackend。
- `presentation/profile_view_model.py` 从同一 PlotSpec/payload 生成详情与表格 DTO；显示值、体系能量及势垒来自 Python 当前结果。势垒只在已显式设置相邻前驱及 TS 时显示，并注明前驱。直接差值不伪装成体系绝对能量；无效值不回显上次有效值。
- `molecule_view.js` 在同一 WebEngine 中增加独立小 canvas：C 灰、H 白、O 红、N 蓝，光照球棍、鼠标旋转、滚轮缩放、双击复位。连接键采用明确的距离/近似共价半径显示启发式，UI 标注“连接键仅为显示推断”，不声称键级已计算。半径取常见 Cordero 数值子集，研究背景见 [Cordero 等，Covalent radii revisited](https://pubs.rsc.org/en/content/articlelanding/2008/dt/b801115j/unauth)。未知元素仍画原子，但不猜连接键。
- 多来源表达式不默认指定某一个分子代表整个体系：列出 value 依赖的来源/作业供显式选择；reference 依赖保留在完整来源清单。没有坐标时显示状态，不使用硬编码分子。分子画面以宽 65%/高 72% 上限适配包围盒，受结构长宽比限制时优先完整容纳，不拉伸原子坐标。
- `inspector_view.js` 用安全 DOM/SVG 绘制详情、两路径概览、关键能量表。概览曲线复用 `curve_runs`，只真实节点可选；主图/概览/表格通过同一 UUID 选择事件联动。二维重叠点可重复点击轮流选择，也可键盘聚焦指定节点。
- 表格新增白名单 `plot_state.step_pairs`，仅保存显式的 `(path_id, entry_id)` 对应组。无映射时逐项显示，另一列为“—”；不按标签或数组位置猜配对。Ctrl/Shift 在不同路径各选一点后，右上菜单可“配对所选步骤”。映射经 SQLite v1 往返验证，异长路径、重复名字不串配。
- 右上菜单接通编辑表达式、定位来源、复制当前数值、隐藏/显示详情及原工作台选项。多来源先展开全部角色/类型/SHA/行号；点击具体来源在只读 Log Viewer 打开经 SHA 核查且限定于该 job 的行号上下文。复制移至 Qt 下一轮事件处理，避免在 WebChannel 回调里直接写剪贴板。只读项目禁用编辑入口。

## 实际验证

主报告：[artifacts/rf4/validation.json](../artifacts/rf4/validation.json)，**22/22 通过**，源码进程 **PID 43864**，Windows Qt/WebEngine，1672×941 DIP、DPR=1、进程兼容掩码 `0xffffff3f`。

- 小视窗确实使用 Three.js，4 个原子、3 条推断连接；坐标来自 RF4 独立日志中 **13–22 行**的 Standard orientation，严格位于绑定 job **2–25 行**内。并核对来源 SHA、作业 ID、parser 版本和合成标记。
- 默认 A/TS1 的相对能量与已明确设置的势垒均为 **+15.060 kcal/mol**，体系能量显示 **−149.976000 Eh**；表格 4 个步骤组的独立 entry IDs 来自生成器的明确映射。
- 真实 Qt 原生鼠标点击表格/概览正确更新所选 UUID、详情和主图；Ctrl 追加选择并配对步骤通过。全部来源清单、原始行定位、分子旋转与双击复位通过。
- 真实多来源表达式经核心计算后显示“请选择来源”，对象数为 0、canvas 为 `display:none`；显式选择来源后才显示对应作业的结构。此次验证修复了空签名状态切换，以及 Three.js 内联 `display:block` 覆盖 `hidden` 导致旧帧仍可见的问题。
- 连续 100 次分子数据切换及实际绘制，第 1/50/100 次均为 **10 objects / 2 geometries**。闲置无持续 RAF，隐藏详情停止分子绘制。此项仅证明资源计数有界，不是 GPU 显存/长期性能测试。
- 当前页面只有一个 WebEngine。中英文、深浅色末尾场景通过，JS 错误 **0**。

剪贴板证据分开记录：最终组合套件用 writer 记录器验证精确复制载荷，避免重复改写系统剪贴板；前一实际 Windows Qt 进程 **PID 27448** 已通过系统剪贴板写入及读回，证据见 [native-clipboard-validation.json](../artifacts/rf4/native-clipboard-validation.json)。普通 Qt 回归另验证守卫后的真实剪贴板读回。该早期进程当时还有独立的多来源隐藏检查失败，因此没有把它的整套运行计为通过。

最终未修改的窗口截图：

- [英文深色 1672×941](../artifacts/rf4/rf4-en-dark-1672x941.png)
- [中文浅色 1672×941](../artifacts/rf4/rf4-cn-light-1672x941.png)

夹具：[tests/fixtures/profile_rf4/README.md](../tests/fixtures/profile_rf4/README.md)、`tools/build_profile_rf4_fixture.py`。这些坐标/能量是明确标记的合成示例，不声称是真实量化计算结果。验收每轮使用独立项目副本，保留 RF0 和用户项目；原始 `.grproj` 夹具不被测试表达式编辑覆盖。

## 源码回归与复现

```powershell
.venv\Scripts\python.exe tools/check_profile_inspector.py
.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'tools');from diagnose_static_runtime import windows_affinity;m,_,s=windows_affinity();s(m['default'] & 0xffffff3f);import pytest;raise SystemExit(pytest.main(['tests/test_structure_preview.py','tests/test_profile_rf4.py','tests/test_workbench.py','tests/test_plot_spec_export.py','tests/test_plot_inspector.py','-q']))"
.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'tools');from diagnose_static_runtime import windows_affinity;m,_,s=windows_affinity();s(m['default'] & 0xffffff3f);import pytest;raise SystemExit(pytest.main(['tests/test_node_editor.py','-q']))"
```

相关回归 **75 passed in 52.84s**；表达式编辑/保存回归 **12 passed in 23.64s**。新增覆盖完整/截断/无效表格、方向优先级、作业隔离、单位、取消、大小限制、缓存复核、来源变化、过期请求、真实剪贴板、无自动步骤配对、显式配对 SQLite 往返及多来源空状态切换。

## 保留范围

RF4 没有实现 RF8 的通用 Structures/Log Viewer 分析模块；此处为能量页的选中作业预览与限定行来源窗口。未重建 EXE，未验证其他平台/高 DPI 或大型真实日志兼容矩阵。完整 2D/窗口适配属于 RF5；新 renderer 的完整导出/审计包迁移属于 RF6；最终参考图和包验收属于 RF7。继续沿用已记录的 G4 兼容掩码，本轮未重新调查默认调度崩溃。
