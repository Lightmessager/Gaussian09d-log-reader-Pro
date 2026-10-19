# UX v2.0 U3 验收记录

## 状态与范围

**U3：导入后引导与旧路径兼容已完成。** U0 完整基线在 U3 阶段记录时仍未完成，现已完成并见 `docs/ux-v2-baseline.zh-CN.md`；U4–U7 当时未启动。本阶段新增导入摘要和作业候选草稿入口，并为不含配方的旧路径提供只读说明、受控转换预览及继续查看路线。

没有更改 SQLite schema、表达式求值算法或反应边确认规则。普通旧路径只在用户逐项确认角色、组成和引用策略后才生成转换草稿；复杂 AST、直接差值与无效路径不会自动重建。独占且完整匹配的旧 node/entry UUID 可在原位转换中保留；共享节点须转到新路径，原路径不变。

## 实现

- `apply_path_recipe` 增加默认兼容的 `identity_policy="regenerate"`，保留既有调用行为；显式 `preserve_exclusive` 仅复用当前路径中唯一、成对匹配的 node/entry 身份，且拒绝其他路径共享、部分/悬空/重复映射。复用节点的显示信息和路径点显示覆盖随身份保留。
- `BuilderDraft.from_project` 分类现有配方、空路径、可支持单引用路径、专家路径和无效路径。转换预览校验项目 UUID/revision、相对路径、唯一零点、作业来源、角色、单物质组成及引用策略确认，不修改原项目。
- 绝对能量与直接差值旧路径不显示可用的原位转换；界面说明限制并提供专家表达式或显式选取作业另建相对能量路径，之后由用户设置零点。
- 搭建器首次打开无配方旧路径时显示旧节点、表达式及当前修订值说明；用户可查看转换预览或继续查看原路径。复杂/直接差值路径保留专家表达式入口。共享节点提供新路径路线。
- 导入成功后显示新增来源与项目总作业数，以及 SCF、Gibbs 热校正和 Gibbs 总量的可用计数；可用数分别标明项目总计与本次新增。作业表展示来源路径、source/job UUID 以区分同名项；勾选只产生物质卡草稿，不按文件顺序推断阶段或确认反应边。
- 首页工作流状态由当前项目、路径、修订结果、保存、来源连接、busy/只读状态派生；其他项目、过期 revision 或已失效来源的结果不会使检查步骤显示就绪。依赖来源失效时，下一步进入计算日志、清除遮挡目标行的筛选并选中该来源，以便重新定位；只读时引导查看来源状态。

主要文件：`src/gaussianreadpro/core/reaction_network.py`、`src/gaussianreadpro/services/controller.py`、`src/gaussianreadpro/ui/workflow_state.py`、`src/gaussianreadpro/ui/reaction_builder_state.py`、`src/gaussianreadpro/ui/reaction_builder.py`、`src/gaussianreadpro/ui/import_summary.py`、`src/gaussianreadpro/ui/main_window.py`、`tests/test_builder_legacy_adapter.py`、`tools/verify_u3_legacy_builder.py`。

## 自动化验证

以下命令均在当前 Windows 工作区运行，退出码为 0：

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_builder_legacy_adapter.py
# 13 passed
.venv\Scripts\python.exe -m pytest -q tests/test_reaction_network.py
# 13 passed
.venv\Scripts\python.exe -m pytest -q tests/test_multi_paths.py
# 3 passed
.venv\Scripts\python.exe -m pytest -q tests/test_expressions.py tests/test_project_management_ux.py tests/test_workbench.py
# 122 passed
.venv\Scripts\python.exe -m compileall -q src/gaussianreadpro
# exit code 0
```

适配测试覆盖转换数值/身份/参考签名、默认重建兼容、部分/悬空/重复身份拒绝、共享节点另建路径、复杂 AST 与绝对能量旧路径不静默转换、导入候选不建立已确认反应边、能量可用计数，以及来源连接失效时将来源步骤标为需处理并路由到重新定位/只读查看。

## Windows Qt 界面检查

命令：

```powershell
$env:QT_QPA_PLATFORM='windows'
.venv\Scripts\python.exe tools/verify_u3_legacy_builder.py
```

结果：退出码 0。脚本使用合成 Gaussian 日志启动 Windows 原生 Qt 后端，检查导入摘要的新增/总计能量、显式候选表的来源路径及 source/job UUID 和选中返回、旧相对路径首次打开时的说明及转换/继续查看入口；并检查绝对能量路径明确隐藏原位转换、显示另建路径入口。另以连接状态为 changed 的结果驱动真实 MainWindow，点击工作流下一步后验证进入计算日志页、自动选中失效来源且“重新定位选中来源”按钮可用。关闭旧路径编辑器后断言 project 与 reaction network 未变化。

截图：[旧路径首次打开窗口](../artifacts/u3_legacy_builder_first_open.png)。已查看生成图像，中文文字可读。脚本设置的逻辑窗口尺寸为 1180×760；这不是 840×680 窄窗口验收。

## 限制与下一阶段

- 桌面检查使用合成数据与程序化选择；未执行真实日志的完整“导入完成 → 用户点击摘要 → 选择作业 → 在主窗口打开搭建器”人工路线。
- 未验证冻结发行包、真实用户项目或其他平台；U0 全面基线在 U3 阶段记录时仍未关闭，现已完成并见 `docs/ux-v2-baseline.zh-CN.md`；历史 S8 综合验收仍未关闭。
- U4 可在此基础上实现可视化阶段画布；不可把本阶段只读旧路径概览当成 U4 画布已完成。
