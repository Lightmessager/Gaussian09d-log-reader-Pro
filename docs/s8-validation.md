# S8 综合验收进度（2026-10-17）

状态：**已启动，尚未通过阶段门槛**。合成连续流程、固定真实日志桌面流程、性能样本和原生界面流程已有证据；全量单进程稳定性及高负载 UI/WebEngine 测量未通过或未完成。

## 本轮改动

- `tools/check_s7.py` 的合成日志补写 Gibbs 热校正行。当前 `gibbs_total` 必须取同一作业的最后 SCF Done 与热校正之和；只写 Gaussian 打印总量的旧夹具已不符合科学规则。
- `ui/profile_view.py` 在图表加载失败转原生二维预览时保留用户的多路径比较选择，防止降级事件把项目的 `compare=true` 擦除。
- `resources/plot/scene3d.js` 先占用路径名与坐标轴标签的屏幕区域，再放置节点标签，减轻紧凑三维产物端的重叠；独立的路径名仍可能贴近节点，密集路径需进一步人工复核。
- `tests/test_s8_flow.py` 新增同一个合成项目的导入 → 同作业 Gibbs 计算与参考 → PlotSpec/离线 HTML 来源审计 → 具名保存 → 新 SessionBackend 重开链路。
- `tools/check_s8_performance.py` 对许可范围内的 cclib Gaussian16 本地真实日志采样解析、SHA 重核、100 节点计算与 PlotSpec/payload 构建，报告在 `artifacts/s8/core-performance.json`。
- `tools/check_s8_real.py` 增加真实日志原生桌面流程，显式为每个导入节点绑定其来源作业的 SCF 能量，检查修订号、QtWebEngine 实际 Plotly 节点迹线、保存/HTML 导出及新会话恢复。验收条件要求路径确有 3 个有效节点，防止空节点列表的 `all()` 真空真值造成误通过；截图前也等待前端稳定帧。

## 实际结果

- `.venv\Scripts\python.exe -m pytest tests/test_s8_flow.py -q`：**1 passed**。四个明确标为 SYNTHETIC 的作业，SCF 与热校正来源行分别为 3、4；相对值为 `0, +0.024, −0.008, −0.025 Eh`，导出审计和重开一致。
- `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests/test_s8_flow.py tests/test_multi_paths.py tests/test_workbench.py::test_gui_heartbeat_while_worker_waits_and_cancel tests/test_workbench.py::test_save_failure_banner_and_retry_do_not_claim_success tests/test_workbench.py::test_missing_sources_never_show_current_valid_numbers tests/test_plot_spec_export.py::test_export_rechecks_current_sources_before_writing tests/test_storage.py::test_real_log_parse_snapshot_roundtrip -q`：**11 passed**，包含三份固定真实 Gaussian16 日志的解析快照落盘。
- 图表导出与产品界面两文件单独运行、排除已知不稳定异步事件用例：**32 passed, 1 deselected**。
- 最终覆盖全部已收集测试的分组回归（均使用 `tools/run_pytest_compat_windows.py`，进程亲和性 `0xffffff3f`）：核心 11 文件 **185 passed, 1 skipped**；界面 10 文件 **107 passed, 1 deselected**；存储 2 文件 **55 passed**；排除的异步图表用例另起进程 **1 passed**。合计 **348 passed, 1 skipped**，四个进程均退出 0。三个分组的文件列表分别为：核心 `test_calculations/test_elements/test_expressions/test_gaussian_analyses/test_parser/test_project_edits/test_reaction_network/test_reference_logs/test_s0_oracle/test_structure_preview/test_units_models`；界面 `test_glass_preferences/test_multi_paths/test_node_editor/test_plot_inspector/test_plot_spec_export/test_product_identity/test_profile_rf4/test_profile_rf6/test_s8_flow/test_workbench`；存储 `test_storage/test_storage_sources`。文件名均位于 `tests/` 且后缀 `.py`。**全套在单个 pytest 进程中仍未稳定通过**，不能把分组汇总改写为单进程全绿。
- `.venv\Scripts\python.exe tools\check_s8_performance.py`：**退出码 0**；最新单次样本为 Windows 11 / Python 3.12.14，3 份真实输入共 792,948 字节，解析 370.737 ms（2.040 MiB/s），三来源指纹检查 1.883 ms；100 节点计算 12.856 ms、PlotSpec 7.333 ms、payload 40.497 ms。另以 1000 条明确合成且只用于显示的来源行在 Qt offscreen 表格中筛选 16.720 ms、滚动 21.055 ms。测量位于 `artifacts/s8/core-performance.json`；`tracemalloc` 峰值只包括 Python 追踪堆，offscreen 表格不代表原生绘制，均不包括 WebEngine/GPU 或跨机器性能结论。
- `.venv\Scripts\python.exe tools\check_s8_real.py`：真实日志原生流程**通过**。使用固定夹具 `dvb_sp.out`、`dvb_gopt.out`、`dvb_ir.out`，SHA 与固定清单逐一相符，SCF 能量来源行及数值一致；3 个节点均有效，首节点为零点，三点相对值均为 `0.0 Eh`（该固定样本的 SCF 值相同）。实际 WebEngine DOM 有 3 点的 `computed-nodes` Plotly 迹线、空警告区，图中与表格均显示 `+0.000 kcal/mol`；保存后新 SessionBackend 打开项目数值一致，HTML 导出成功，controller 错误为空。Qt DPR 1.25，逻辑窗口 1440×900。报告及截图：`artifacts/s8/real-native/92eb19ada3b54c7185e145652b59afd3/validation.json`、`real-gaussian-scf.png`；同目录含保存项目与 HTML。真实日志不是合成数值，但它们的能量相同，故不能用来证明有势垒的路径形状。
- `.venv\Scripts\python.exe -c "...runpy.run_path('tools/check_s7.py',run_name='__main__')"`（先应用进程亲和性 `0xffffff3f`）：受限进程中首图加载失败；正常桌面权限下更新旧脚本的 Plotly 容器选择器、比较开关时序和现行 Three.js 断言后，**15/15 通过**。标签避让调整后的最新报告 `artifacts/s7/validation.json`，项目与独立运行目录 `artifacts/s7/runs/bd412e4bb5d74a928926e0c912e0ec08/`。检查包括真实鼠标点选、表格联动、局部势垒、视口/标签状态、双路径、二维四格式导出、离线 HTML 三维、Three 场景/PNG、深浅主题/紧凑窗、100 次图表更新、过期事件、WebGL 降级及保存/全新窗口恢复；controller/JS 错误及阻断远程请求均为空。数据均为明确标为 SYNTHETIC 的作业；这证明本机正常桌面权限下的该脚本流程，不扩大为真实化学样本或其他平台通过。
- 实际 Qt 截图：`artifacts/s7/profile-2d.png`、`profile-3d.png`、`profile-en-dark.png`、`profile-compact.png`。宽窗约 1540×1080 逻辑尺寸，宽窗 PNG 1925×1350 像素（DPR 约 1.25）。已人工查看：曲线、点、单位、零线、两条路径和三维路径类别可辨。紧凑三维产物 P 的数值标签经避让后移开路径名，但路径名仍贴近节点，密集路径需继续复核。
- 现行 `tools/check_profile_rf7.py --runtime source --phase primary --case s8` 在正常桌面权限下验证了应用身份、Qt DPR 1.0 与 1672×941 窗口，但随后等待无结构夹具的分子对象超时；报告 `artifacts/rf7/source-primary-s8-64cd66fe/validation.json`，不记为 RF7 主流程通过。

## 全量回归的失败边界

使用项目记录的进程亲和性运行 `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q`，第一个可复现失败是新路径建立后 `compare` 被图表原生降级清除。该产品行为已修复，相关多路径与图表组重跑通过。

修复后 `-x -q` 长序列得到 **188 passed, 1 skipped, 1 failed**：失败为 `test_expression_save_footer_fits_840_with_long_project_path`，编辑器要求 840×680，实际高度被 Qt 抬到 976；该测试单独运行通过，连同邻近图表文件运行也通过，尚未定位长序列状态影响。先前无 `-x` 的全量运行在约 61% 处又于 `test_s8_continuous_scientific_flow` 新建恢复仓库时原生中止，栈显示主线程等待仓库执行器返回；该测试独立和界面分组运行均通过。分组结果覆盖所有已收集测试，但不能证明单进程长跑稳定。

## 尚缺的 S8 验收

1. Windows 原生综合流程已用合成夹具通过 15 项；另有三份固定真实日志完成导入、SCF 节点绑定、相对能量、实际绘图、导出、保存和重开。仍需有非零能量差/势垒的代表性真实路径和更多 DPI/负载证据。CUA 当前仍无可访问应用窗口，正常桌面权限可运行 Qt 原生脚本；紧凑三维产物端标签仍需密集路径人工复核。
2. 在长序列中定位编辑器高度断言波动和 SQLite/Qt 原生中止，再完成一次全量回归。
3. 在真实 UI 上补主线程响应、100 次连续更新的主进程与 WebEngine 子进程内存、导出用时及大文件操作记录；约 1000 行表格目前仅有 offscreen 合成行样本，原生滚动还待观察。GPU 显存及 macOS/Linux 仍未实测。

现阶段完成的是可复核的核心链路与部分失败情境，**S8 不标记完成**。此前 L4/L5 的桌面窗口限制仍在，不能由本轮离屏或核心测试覆盖。
