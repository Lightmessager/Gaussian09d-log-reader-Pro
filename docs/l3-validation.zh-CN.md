# L3 项目命名与文件生命周期验收

日期：2026-10-17

## 实现

- `MainWindow` 新建项目时询问显示名称；首次“保存项目”以该名称预填 `.grproj` 文件名。已保存项目的标题和顶栏显示项目文件名。
- 首页最近项目列表右键菜单提供“打开”“从最近项目移除”“重命名项目文件…”和“删除项目文件…”。删除确认框展示完整路径，并明确来源日志等其他文件不受影响。
- `ProjectController` 将最近列表修改、改名和删除作为串行操作提交给 `SessionBackend`。当前项目改名会保存当前修订、关闭连接、同目录改名并重新打开；失败时尝试恢复原文件路径和活动会话。非当前项目改名/删除不关闭活动项目。
- 删除当前项目后 UI 返回无活动项目状态。删除仅 unlink 被选中的 `.grproj` 主文件；独立自动恢复副本保留在恢复目录，可从恢复副本入口手动恢复。
- `LocalPreferences` 新增规范化路径的最近项目移除/替换；Windows 路径按 normcase 去重。

## 验收结果

- 通过：`$env:QT_QPA_PLATFORM='offscreen'; .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_workbench.py::test_project_rename_delete_and_recent_removal_are_scoped tests/test_workbench.py::test_backend_failed_open_preserves_active_session tests/test_glass_preferences.py`（14 passed）。
- 通过：`$env:QT_QPA_PLATFORM='offscreen'; .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_workbench.py`（28 passed（68.80 秒））。新增生命周期用例检查改名后 UUID/来源路径保持、偏好路径更新、仅移除最近不触碰磁盘、删除选中文件不删其他项目。
- 全仓库测试尝试未完成：运行约 43% 后 Windows Python/PySide6 原生 access violation；重试在 pytest 收集 `test_glass_preferences.py` 导入 `shiboken6` 时同类 access violation。专项和 `test_workbench.py` 均独立通过。完整测试集仍需在稳定的 Qt/Python 环境回归。

## 尚未完整验证

- 未做人工桌面确认流程，也未注入文件系统只读/占用故障验证回滚；对应异常处理已实现并保留旧状态恢复路径。
- 删除项目主文件后恢复副本仍可见，这是为遵守“只删除选中的 `.grproj` 文件”而保留的既有恢复机制。
- L2 能量图深浅主题视觉验收尚存项目书记录中的 WebEngine 限制；本阶段依用户指示继续完成 L3。
