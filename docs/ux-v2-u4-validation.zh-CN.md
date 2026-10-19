# UX v2 U4 验收记录：反应阶段画布与局部详情

日期：2026-10-18  
范围：项目书 U4；未包含 U5 的能量来源诊断与保存状态机，也未包含 U6 草稿保护和完整键盘流程。

## 本阶段交付

- 搭建器现在有物质库、阶段画布、阶段列表替代视图、局部详情/预览页签和固定页脚。阶段画布和检查器始终读取同一份 `BuilderDraft` 网络；编辑动作经命令验证后提交。
- 画布显示角色、组成、能量项、零点和缺值状态，支持分支/回汇连线、选择及拖动布局。组成区与能量区分开；不唯一绑定作业的物质不能被静默转换为能量项。
- 增加草稿级撤销/重做。被拒绝的命令不会改变草稿；布局和标签编辑不清除科学确认，组成、能量项、连接、角色和零点变更会清除受影响确认，并在详情区说明。
- 对旧路径保留“未指定”角色兼容；画布位置独立存于布局草稿，不进入科学 AST 或能量坐标。

## 验证证据

- Windows Qt 窗口烟测：运行 `.venv\Scripts\python.exe tools\verify_u4_reaction_canvas.py`，退出码 0。窗口实际尺寸 **840×680**；使用 4 个阶段和 4 条连接构造分支与回汇；所选阶段可见；检查器角色字段可通过水平滚动进入视口；阶段列表替代视图可切换且可见；撤销、重做、应用、预览、网络保存、项目保存和取消按钮均位于窗口内。
- 截图：[`artifacts/ux-v2/u4/reaction_canvas_840x680.png`](../artifacts/ux-v2/u4/reaction_canvas_840x680.png)。截图显示固定页脚和 840×680 的实际窗口布局。
- 回归命令：`$env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe tools/run_pytest_compat_windows.py -q tests/test_reaction_canvas.py tests/test_reaction_network.py tests/test_builder_legacy_adapter.py tests/test_multi_paths.py tests/test_workbench.py`；最终代码结果 **76 passed in 81.30s**。
- 编译检查：`.venv\Scripts\python.exe -m compileall -q src tests tools/verify_u4_reaction_canvas.py`；退出码 0。
- 资源检查：`en_US.json`、`zh_CN.json` 均可解析，重复键数为 0。

## 限制与未覆盖项

- 840×680 下物质库、画布和详情栏较窄，侧栏字段可用滚动条访问；画布上不同层级可能需要水平滚动，截图中的视口显示所选 Product 卡。此结果确认控件可达，不代表所有卡片能同时呈现在窄窗口中。更宽窗口的视觉密度与高 DPI 矩阵未在 U4 验收。
- 这是合成项目窗口烟测，不是冻结 EXE 验收，也未覆盖真实日志的完整预览、应用和保存流程。
- 工作目录没有 `.git`，因此没有 Git 状态、差异或提交证据可提供。

## 后续阶段

U4 通过以上代码、回归和窗口检查；下一步按项目书进入 U5：能量检查与可靠的应用/保存。U4 阶段记录当时 U0 的基线尚未完成；现已完成，见 `docs/ux-v2-baseline.zh-CN.md`。
