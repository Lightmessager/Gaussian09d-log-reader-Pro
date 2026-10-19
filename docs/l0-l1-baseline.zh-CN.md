# L0–L1 基线与验收记录

日期：2026-10-17

## L0 基线

- 首页最近项目位于 `ui/main_window.py` 的首页列表；双击或“打开选中项目”进入项目，顶部“最近”菜单也提供打开入口。项目操作菜单含保存、另存、导入、来源与路径节点操作。当前项目路径由 SessionView 提供。
- `services/session.py::SessionBackend` 持有当前 `ProjectRepository`。保存经 RecoveryService/仓库完成；会话释放和 `shutdown()` 会关闭恢复服务与仓库。项目打开期间 SQLite 仓库连接仍由该后端持有，因此文件生命周期操作不能在 UI 线程直接改动。
- 当前元素显示入口：`ui/analysis_pages.py::StructureCanvas` 的原子球标签；同页结构坐标表；该表的 CSV 导出复用显示字段。表中已有“原子序数”数值列。`resources/plot/molecule_view.js` 的三维预览仅画球棍并按原子序数着色，不绘制文字元素名。结构数据由 `services/structure_preview.py` 与 `services/gaussian_analyses.py` 保留 `atomic_number`。
- 已有可用受控结构样本：`tests/test_structure_preview.py` 中的合成 orientation，含原子序数 6 与 1；测试同时覆盖 0 和 119 的非法输入。真实结构测试日志未发现作为验收夹具的 B 样本，因此 L1 映射验收采用元素符号单元样例，不修改日志或项目数据。
- 能量页路径入口分布在紧凑路径页签、顶部路径列表/创建入口及“项目操作 → 路径节点”菜单；NewPathDialog 处理现有节点选择或空路径创建。`services/controller.py::add_node` 新节点表达式为空。当前运行环境未执行桌面端“导入 → 新建路径 → 新建节点 → 表达式 → 保存”的完整人工流程，该项仍是 L0 的验收限制。
- L0 主题对比基线按阶段要求留待 L2；本阶段未改主题或科学计算代码。

## L1 修改与验收

- 新增 `core/elements.py`，集中提供 1–118 序数符号查询，非法输入返回 `?`。
- 结构画布改用共用查询；结构坐标表/CSV 增加元素符号列，并保留准确的数值“原子序数”列。
- 原子序数、坐标和来源解析均未改写；分子预览没有元素文字标签，无需新增映射调用。旋转及结构导出路径未改动。
- `.venv\\Scripts\\python.exe -m pytest tests/test_elements.py tests/test_structure_preview.py -q`：23 passed。
- `.venv\\Scripts\\python.exe -m pytest tests -q`：327 passed, 1 skipped, 3 failed。失败为既有多路径比较状态、图表事件 dirty 状态、表达式弹窗 840×680 尺寸断言（`test_multi_paths.py::test_create_colored_path_inherits_reference_and_survives_save`、`test_plot_spec_export.py::test_chart_events_are_guarded_and_plot_state_survives_save`、`test_product_identity.py::test_expression_save_footer_fits_840_with_long_project_path`）；均与元素映射无关。
- 旋转事件/坐标旋转代码、结构 CSV 导出代码未改动；针对性结构预览回归通过。全量回归的三个失败需作为已有待处理项跟踪，本阶段没有扩展其范围。

## L2 实施进度

- 全局深色 token、玻璃背景辉光/边框、自绘结构视图及能量图主题色已优化；浅色的控件边框、禁用文字也提升到项目对比度目标。
- 深浅主题首页和结构页桌面截图、对比度数字及验证限制见 `docs/l2-validation.zh-CN.md`。
- 深浅主题、工作台、图表和结构相关回归 77 项通过；最终色值改动后聚焦回归 15 项通过。
- 主能量图 WebEngine 页面在本机加载失败，无法取得新主题实际图表截图；L2 未完整验收，不进入 L3。
