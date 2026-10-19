# UX v2 U5 验收记录：能量预检与可靠的应用/保存

日期：2026-10-18  
范围：项目书 U5。U5 阶段记录当时 U0 基线仍未完成，现已完成并见 `docs/ux-v2-baseline.zh-CN.md`；本记录不代表 U6 草稿保护、U7 冻结包或真实项目日志验收。

## 实施内容

- 配方预检和来源指纹复核在现有 `ProjectController` 单线程 worker 中执行。结果带项目/路径 UUID、项目修订、草稿代次、网络与选项摘要、worker token；控制器或搭建器会丢弃过期结果，应用时再次核对摘要和身份。
- worker 读取已准备的项目快照，调用 `inspect_sources`、`calculation_snapshot`、`calculate_path`。预览按准备后项目的路径点身份显示能量；来源改变或失联时结果无效，不显示旧值为当前结果。
- 用户点击“应用并保存”或“仅应用”时会重新核验来源指纹；草稿变化或重新核验期间会清除旧数值。若日志在预览通过后变化，新的来源错误会阻止应用。
- 预览页增加错误/警告列表。阶段、反应连接和来源问题可以分别定位到详情、画布或来源证据。配方核对缺项会带阶段/连接 UUID；NOT FOUND 保留缺值，数字零仍作为有效值显示。
- 页脚主按钮按“预检 → 应用一次 → 保存项目”执行；首次保存只在应用成功后询问路径。取消或写盘失败保留已应用的内存项目，下一次主操作只重试保存。菜单中的“仅应用到当前项目”保留为不写盘路线。
- 中文和英文资源补齐了 U5 状态、诊断及操作文案。

## 验证结果

### U5 专项用例

U5 专项共 **13 个用例**，均以单个测试项启动独立进程，全部 **1 passed**：

```powershell
.\.venv\Scripts\python.exe tools/run_pytest_compat_windows.py "tests/test_builder_save_flow.py::test_source_change_after_preview_is_rechecked_before_apply"
```

测试覆盖：`test_changed_source_invalidates_preview`（SHA 改变和文件缺失）、`test_preview_uses_same_job_scftotal_and_both_zero_points`、`test_not_found_transition_state_preview_never_has_a_numeric_energy`、`test_wrong_base_revision_cannot_start_a_preview`、`test_project_revision_change_invalidates_cached_preview_before_apply`、`test_source_change_after_preview_is_rechecked_before_apply`。数值检查覆盖同一作业的 SCF 与 Gibbs 校正及各自来源行；绝对值 −10/−9.98/−10.02 Eh；反应物零点 0/+0.02/−0.02 Eh；产物零点 +0.02/+0.04/0 Eh；合法零值；固定 kcal/mol 换算和两个局部步差。SHA 改变、文件缺失、预览后源文件变化、草稿代次变化和项目修订变化均不能使用过期预览应用。

其余有状态 Qt 流程用例各自在新进程运行，均为 **1 passed**：

- `test_apply_save_cancel_then_retry_does_not_duplicate_nodes`
- `test_save_failure_retries_io_only`
- `test_apply_only_stops_before_project_file_save`
- `test_unrelated_completion_cannot_finish_a_save`
- `test_stale_preview_is_ignored_after_draft_generation_changes`
- `test_preview_diagnostic_clicks_to_connection_and_source_evidence`

合并多个 Qt 用例到同一个 pytest 进程时，进程有时会在用例/清理阶段触发 Windows 原生 abort，因此专项用例采用单项隔离运行，并记录原生中止限制。

### 相关回归

以下每个文件都通过 `tools/run_pytest_compat_windows.py` 单独运行：

| 测试文件 | 结果 |
|---|---:|
| `tests/test_reaction_network.py` | 13 passed |
| `tests/test_builder_legacy_adapter.py` | 13 passed |
| `tests/test_reaction_canvas.py` | 18 passed |
| `tests/test_multi_paths.py` | 3 passed |
| `tests/test_s8_flow.py` | 1 passed |
| `tests/test_workbench.py` | 29 passed |
| `tests/test_storage.py` | 38 passed |
| `tests/test_storage_sources.py` | 17 passed |
| `tests/test_project_management_ux.py` | 49 passed |
| `tests/test_workflow_actions.py` | 8 passed |

`.venv\Scripts\python.exe -m compileall -q src tests tools/verify_u5_apply_save.py` 退出码 0。`zh_CN.json` 与 `en_US.json` 都可解析，各有 598 项，无重复键。

### Windows Qt 桌面烟测

运行 `.venv\Scripts\python.exe tools/verify_u5_apply_save.py`，退出码 0。真实显示的 **840×680** 原生 Qt 搭建窗口中，应用并保存、更多操作、预览、关系网保存、项目文件保存和取消按钮都在窗口内。合成三日志项目的主路线在第一次受控写盘失败后进入“已应用、尚未保存”；第二次只调用保存，保留相同项目修订、3 个节点和 3 个路径点后显示“已保存”。

![U5 840×680 原生 Qt 窗口](/D:/Project/GaussianReadPro/artifacts/ux-v2/u5/apply_save_840x680.png)

## 限制与未覆盖项

- 多个 Qt 场景放在同一 pytest 进程时，Windows 原生进程触发过 `Fatal Python error: Aborted`，包括在 7 个核心用例输出通过标记后、pytest 汇总前的清理阶段。13 个 U5 专项用例逐项在新进程运行并通过。该原生中止已保留为验收限制，没有将整文件单进程运行描述为通过。
- 桌面烟测使用合成 Gaussian 日志和临时项目，验证的是源码版原生 Qt 流程；未使用用户的真实项目/日志，也未验证冻结包。
- 工作目录没有 `.git`，因此没有 Git 状态、差异或提交证据。

### U6 期间的回归复测

2026-10-18 为 U6 回归再次运行完整文件：

```powershell
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_builder_save_flow.py -q
```

结果为 **13 passed, 22.64s，退出码 0**。本次复测没有重现上面记录的单进程原生中止；保留历史记录以区分两次运行结果。

## 后续阶段

U5 源码实现、分组回归及合成项目桌面路线已完成；后续 U6 实施与回归记录见 `docs/ux-v2-u6-validation.zh-CN.md`。U0 基线在 U5 阶段记录时仍未完成，现已完成并见 `docs/ux-v2-baseline.zh-CN.md`。
