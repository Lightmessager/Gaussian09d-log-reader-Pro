# UX v2.0 基线审计（U0）

## 状态

**U0 基线采集已完成（2026-10-18），并于 19:25 +08:00 做了只读复核。** U1–U6 的实现与阶段验证见各自验收记录；当前工作状态见 `AI_HANDOFF.md` 与 `docs/handoff.md`。复核没有改业务逻辑。

- 冻结版运行证据：[`runtime-observations.json`](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/runtime-observations.json)
- 合并后的机器记录：[`baseline.json`](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/baseline.json)
- 最新源码/打包静态采集：[`baseline.json`](../artifacts/ux-v2/runs/9601167a67ef412cadc6563bbf5e6087/baseline.json)
- 19:25 只读静态复采：[`baseline.json`](../artifacts/ux-v2/runs/f418163bef5b461786b9c97d670e7773/baseline.json)；[本机桌面复核记录](../artifacts/ux-v2/runs/f418163bef5b461786b9c97d670e7773/desktop-recheck-notes.md)

重跑只读静态采集：

```powershell
.venv\Scripts\python.exe tools\check_ux_v2.py
```

## 来源与冻结包

源码、交接记录和项目书的阶段状态已核对。源码与 EXE 的版本标签同为 `v.1.0`，但 EXE 是 2026-10-17 22:19 构建，`src/gaussianreadpro/ui/main_window.py` 修改时间为 2026-10-18 14:58；不能据相同版本号认为它含 U1–U6 当前界面。

| 对象 | 路径/版本 | 文件信息 | 结论 |
|---|---|---|---|
| 当前源码 | `src/gaussianreadpro`，版本 `1.0` / `v.1.0` | 静态采集器记录核心文件 SHA-256 | 当前源码包含 U1–U6 实现 |
| 当前可用冻结包 | `dist/GaussianReaderPro/GaussianReaderPro.exe`，`1.0` / `v.1.0` | 9,768,007 字节；SHA-256 `d6b3b95b6f80c6ef104d747632eb7a5e0d3ad1b7bc1e101a70575fe86c134d49`；build manifest 中的 SHA 与实文件一致 | 通过本机可见 UI 实际运行 |
| 冻结包模块 | `gaussianreadpro.ui.reaction_builder`、`gaussianreadpro.core.reaction_network` | `ReactionBuilderDialog` 类以及 `reaction_network` 模块均在当前 EXE 的 PyInstaller PYZ 代码对象中 | 证明模块存在，不证明当前 UX 入口已打包 |
| 较旧候选包 | `dist/GaussianReadPro/GaussianReadPro.exe`、`dist/GaussianReadPro-S0/GaussianReadPro-S0.exe` | 两者 PYZ 均不含上述两个模块 | 不是本轮运行的 EXE |

因此，本报告将冻结版运行现象与当前源码回归结果分开记录。冻结版展示的是构建时 UI；当前源码的 U1/U2 可见入口和保存行为由本机 Qt 回归脚本另验。U0 不重打包。

## 桌面与场景记录

冻结版通过隔离偏好/恢复目录启动；只打开 `artifacts` 中的样本。Computer Use 返回的应用窗口截图尺寸为 **1442×951**。本机只有 `P2410R2` 一台 2048×1152 显示器；PySide6/Qt 6.12.0 报告主屏 `devicePixelRatio() = 1.25`，锁文件版本也为 6.12.0，且未设置 Qt 缩放环境变量。独立 Win32 探针在创建 Qt 应用前处于 DPI-unaware 状态（返回 96 DPI）；创建 `QGuiApplication` 后进程为 Per-Monitor DPI Aware，屏幕 DPR 为 1.25，因此采用 Qt 屏幕值。Computer Use 的窗口 ID 不透明，无法直接读取冻结窗口的 `QWidget.devicePixelRatioF()`，故表中 DPR 记为唯一显示器的有效 DPR 1.25；这是屏幕 DPR，不伪称为直接读取了窗口属性。

| 场景 | 实际观察 | 证据 |
|---|---|---|
| 无项目 | 首页计数为 0；可见“导入日志”“打开已有项目”；“继续上次工作”禁用。最近菜单为空。 | [首页截图](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/no-project-0.png)，[最近菜单](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/no-project-recent-0.png) |
| 普通导入路径 | 通过可见“打开”和系统文件选择器打开 `artifacts/rf0/profile-replica.grproj`；8 个来源、8 个节点、8 个路径项、2 条路径；无 `reaction_network_v1`，能量页显示无当前有效结果。 | [普通路径截图](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/ordinary-path-energy.png) |
| 合成配方路径 | 本轮复制的三阶段 `R → TS → P` 夹具经可见“打开”载入；能量图为 R `+0.000`、TS `+12.550`、P `−12.550 kcal/mol`；选中 TS 显示来源和作业信息。结构预览提示无可用结构。只核对 UI 呈现，不宣称化学计算正确。 | [配方能量图](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/recipe-path-current.png) |

## 可见入口的实际路由

- 能量页可见“+”点击后打开标题“新增反应路径”的 `QApplication.NewPathDialog`，其中有路径名、颜色、已有节点列表和“创建并比较/取消”。它不是完整 `ReactionBuilderDialog`。本轮按 Escape 取消，未创建路径。[对话框截图](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/recipe-plus-dialog-current.png)
- “设置”打开应用内顶栏下拉菜单，列出语言、主题、视觉/动态效果和“项目操作”。点击“项目操作”仅高亮；未展开可辨认子菜单，也未出现新窗口。Computer Use 未暴露这个菜单的 Qt QObject 类。[设置截图](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/recipe-settings-menu-current.png)
- “最近”打开应用内顶栏下拉菜单，列出项目路径；菜单本身没有重命名动作，点击它未切换主窗口。无项目时显示“暂无最近项目”。Computer Use 未暴露该菜单的 Qt QObject 类。[最近截图](../artifacts/ux-v2/runs/e985288f82724c7d8bd35f73f796cb85/recipe-recent-menu-current.png)

## F01–F12 现象与回归断言

| 编号 | 冻结版/当前源码记录 | 对应回归断言或证据 |
|---|---|---|
| F01 | 冻结能量页有新增路径“+”，无常驻“编辑反应路径”。 | 当前源码：`test_default_energy_view_has_visible_builder_and_save_actions`；本轮 U1 桌面脚本检查按钮在顶栏内可见、可用。 |
| F02 | 冻结版“+”打开 `QApplication.NewPathDialog`，不是完整编辑器。 | 当前源码：`test_new_reaction_path_action_opens_builder_with_new_path_draft`、`test_chart_fallback_keeps_native_builder_entry`。 |
| F03 | 冻结版页头无项目名/保存状态按钮，文件名只在窗口标题中出现。 | 当前源码：`test_default_energy_view_has_visible_builder_and_save_actions`；U1 桌面记录检查项目名、保存按钮和状态。 |
| F04 | 冻结“最近”菜单只有打开路径，改名入口不在该菜单中。 | 当前源码的最近项目操作见 `docs/ux-v2-u2-validation.zh-CN.md` 与 U2 桌面证据。 |
| F05 | 冻结版没有可见项目名动作，未保存项目改名无法从可见入口复现。 | 当前源码由 U2 的首次保存取消/失败及项目名测试覆盖。 |
| F06 | 本轮当前源码受控首存：取消保留名称；合成写盘失败保留名称；重试成功并清除暂存名。 | `test_first_save_failure_keeps_name_and_retry_saves_it_as_filename`、`test_canceling_first_save_keeps_unsaved_name_without_claiming_failure`；本轮 U2 桌面脚本四项结果均为 `true`。 |
| F07 | 冻结侧栏可见“日志查看器”，但未确认源文件专属导航和切页恢复；当前源码恢复“计算日志”入口。 | `test_sources_navigation_uses_calculation_log_label`。 |
| F08 | 冻结版可见“+”不能到完整搭建器；包内确有搭建器模块。 | 本轮当前源码 U1 桌面脚本点击可见按钮，实际打开 `ReactionBuilderDialog`，活动路径 UUID 一致。 |
| F09 | 普通项目能量页无有效能量；冻结入口不能到搭建器，未在该包复现阶段转换。 | 当前源码旧路径适配见 `tests/test_builder_legacy_adapter.py`；U0 不将包内模块存在当成转换已验。 |
| F10 | 冻结版未到搭建器，无法复现预览/应用/保存次序。 | 当前源码保存状态机见 `tests/test_builder_save_flow.py`。 |
| F11 | 冻结版未到搭建器，无法复现草稿关闭守卫。 | 当前源码草稿保护见 `tests/test_builder_drafts.py`。 |
| F12 | 冻结版默认页能见“+”，但点击到路径容器对话框而非完整编辑器。 | 当前源码 U1 桌面脚本与入口测试从可见按钮打开完整编辑器。 |

### 本轮源码桌面回归

U1 命令：

```powershell
.venv\Scripts\python.exe tools\check_workflow_actions_u1.py
```

本轮退出码 0，Windows Qt 窗口 840×680。搭建器、保存、项目名和保存状态控件都在顶栏内；点击可见搭建器按钮实际打开 `ReactionBuilderDialog`，活动路径 UUID 匹配。证据：[机器记录](../artifacts/ux-v2/u1/desktop-runs/1450211f5e6f4a83ae428e7d74a12b47/u1-desktop-evidence.json)。

U2 命令：

```powershell
.venv\Scripts\python.exe tools\check_project_management_u2.py
```

本轮退出码 0，仅操作 `artifacts/ux-v2/u2/desktop-runs/` 中的合成项目。首次保存取消/失败/重试状态全为 `true`；最近项目五个操作按钮在 840×680 中可见并可聚焦。证据：[机器记录](../artifacts/ux-v2/u2/desktop-runs/d0322556d05b405cb466c474ad40e6c3/u2-desktop-evidence.json)。

## U0 验收结论

- [x] 核对交接、当前源码与可用入口；记录冻结 EXE 路径、版本、实文件 SHA-256 和清单一致性。
- [x] 无项目、普通路径、合成配方路径均从当前冻结版实际打开并记录截图尺寸与当前显示器 DPR。
- [x] 在默认能量页通过可见“+”、设置、最近操作；记录实际对话框/菜单路由和未展开的子菜单限制。
- [x] 核验冻结包中 ReactionBuilderDialog 所在模块与 reaction_network 模块；明确冻结包落后于当前 UX 源码。
- [x] 当前源码中受控复现首次保存取消、写盘失败和重试；只用合成项目。
- [x] 保存 F01–F12 现象表和当前源码 U1/U2 可重复回归证据。

**U0 基线完成并已复核。** 本轮静态采集退出码 0；冻结包 SHA 与初次 U0 采集相同。本机复核再次确认冻结包“+”仍进入路径容器对话框，项目操作菜单仍在设置/最近入口中；无项目与普通路径的完整场景证据继续引用同一 SHA 对应的初次 U0 截图。当前源码与冻结包仍不一致；复核未重打包，也未修改业务代码。
