# UX v2 U7 验收：用户路线、真实日志与交接

日期：2026-10-18  
范围：U7 源码验收。用户未要求生成发行包，因此未重建冻结包。

后续：用户另行启动 U8，已构建并验收 2.0.0 Windows 便携包；冻结包及 WebEngine 结果见 [`U8 验收报告`](ux-v2-u8-validation.zh-CN.md)。本页保留 U7 当时的源码阶段范围与结论。

## 结果

U7 源码验收完成。合成数据桌面路线从默认首页开始，通过可见入口完成项目新建与改名、日志导入、作业选择、两条不同颜色路径搭建、反应物零点、能量预检、应用并保存、含硼结构检查、能量图和 HTML 导出；随后新 Python 进程重开项目并比对路径 UUID、表达式摘要、零点、物种绑定/星标及图表数据。

真实 Gaussian16 日志单独完成来源 SHA、SCF 作业与原始行选择、项目保存和新 SessionBackend 重开。三份真实样本的相对 SCF 能量均为 0 Hartree；这组等能量日志不作为非零势垒证据。合成夹具明确标注，与真实日志证据分开。

本机 WebEngine 无法加载本地能量图页面。主窗口显示加载失败提示，并成功切换到原生二维图，显示夹具的 0、+0.02、−0.02 Hartree（约 0、+12.550、−12.550 kcal/mol）；HTML 导出目录和文件生成成功。U7 因此验证了原生降级路线，但没有验证本机 WebEngine/3D 页面运行或冻结包里的页面运行。

## 修复与验证脚本调整

- `ReactionBuilderDialog._sync_after_apply()` 在应用成功并重载配方后刷新草稿干净基线。之前保存第一条路径后，新建下一条路径会误报“未应用的草稿”；新增 `test_saved_path_can_create_next_path_without_exit_prompt`，先复现失败，再以最小修改修复。
- U7 验收脚本通过 `MainWindow.close()` 走真实退出守卫。首次脚本尝试在导出/工作区写入尚忙时直接调用 `controller.close()`；控制器按设计拒绝了关闭请求，脚本却继续等待。本次修正验收脚本，在关闭事件完成后才启动新进程核对。
- 验收脚本记录本地页面失败原因、原生后备是否可见，以及真实数据文件名、SHA 和 SCF 来源行；真实日志本身不复制到 U7 产物目录。

## 自动化验证

所有下列命令退出码为 0。

| 命令 | 结果 |
|---|---:|
| `.venv\Scripts\python.exe tools\check_ux_v2_u7.py` | 退出 0；2 条合成路径、3 份真实日志往返，完整报告见 [`u7-validation.json`](../artifacts/ux-v2/u7/u7-validation.json) |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_reference_logs.py` | 4 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_builder_save_flow.py::test_saved_path_can_create_next_path_without_exit_prompt` | 1 passed（先前红测失败，修复后通过） |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_builder_save_flow.py` | 14 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_builder_drafts.py` | 37 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_reaction_network.py` | 13 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_storage.py` | 38 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q tests\test_builder_legacy_adapter.py tests\test_workflow_actions.py tests\test_project_management_ux.py tests\test_storage_sources.py` | 87 passed |

覆盖包含无配方/旧配方与复杂 AST 保留、同名来源按 UUID 绑定、预览后来源改变、缺少数值时不造零、保存失败后的 I/O 重试、草稿保留/恢复/只读导出、路径退出守卫及只读工作流动作。未运行整个仓库的单进程全量测试。

## 原生桌面证据

本次验收运行目录为 `artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/`。桌面流程从空项目首页开始，控件点击走主窗口和 ReactionBuilderDialog 的可见动作；系统文件/文本对话框返回值由验收脚本提供确定输入。

- [能量图截图](../artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/synthetic-route/energy-profile.png)：可见页面加载失败提示及原生二维后备曲线。
- [结构截图](../artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/synthetic-route/structure-boron.png)：第一行元素为 B、原子序数为 5。
- [导入摘要截图](../artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/synthetic-route/import-summary.png)。
- [新进程重开状态](../artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/synthetic-route/reopened.json)：项目 UUID、2 个路径、2 份配方摘要、反应物零点、3 个物种及 2 条图表曲线均与关闭前状态匹配。
- [合成能量 HTML 导出](../artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/synthetic-route/profile-html/)：`profile.html`、`plot.json`、`data.csv`、`sources.csv`、`manifest.json` 和本地资源均生成。

两条路径分别使用 `#7450af` 与 `#52cdb8`，具有独立 UUID 和三阶段网络；R 物种星标、全部物种到 source/job 的绑定、每条路径反应物零点及节点表达式摘要都在新进程结果中核对。

## 真实日志来源与往返

样本清单和许可说明位于 `tests/fixtures/reference/expected.json` 与 `tests/fixtures/reference/README.md`。每个日志 SHA 与清单一致，选择的 SCF 能量及来源行如下：

| 文件 | SHA-256 | SCF 来源行 | 原始值 |
|---|---|---:|---:|
| `dvb_sp.out` | `682ccce14c07e99e8cdbab7e20e1d7038ca56b5d6d553223595314f3ebaa0ca7` | 3857 | −382.308266602 |
| `dvb_gopt.out` | `f4e280b32b0d9f25ac7a21cfe47e810fe5cecb8b669e8d9751329a0ffded260d` | 2785 | −382.308266602 |
| `dvb_ir.out` | `bc1a21de15ada135d5188b11d44226389022d92488ddfa8163ba7d4d713e5061` | 457 | −382.308266602 |

真实样本项目保存在 `artifacts/ux-v2/u7/2ac03b009a5846bfa5209f4d458c1f45/real-roundtrip/real-source-roundtrip.grproj`，由独立 SessionBackend 重新打开；项目 UUID 与三条相对能量均一致。原始 `.out` 文件仍留在本地 reference fixture，未复制进 U7 运行目录。

## 范围与限制

- 未按项目书的条件打包：本轮没有用户要求发行包，冻结包构建、审计和 EXE 桌面路线未执行。
- 本机 WebEngine 报告“本地图表页面加载失败”，所以 3D 页面、浏览器端 HTML 实际打开和冻结包渲染没有本轮证据；原生二维后备、数据、截图与导出文件生成已通过。
- 真实三日志的能量完全相同，只验证来源解析/作业行/保存往返，不代表反应路径或势垒。
- 工作区没有 `.git`，无法提供 Git 分支、提交或 diff 状态。

## 阶段状态

U7 源码路线、真实日志往返、兼容性分组测试和交接记录已完成。U0–U7 源码/本机合成路线验收可关闭；冻结发行包只有在用户明确要求交付包后再单独验证。
