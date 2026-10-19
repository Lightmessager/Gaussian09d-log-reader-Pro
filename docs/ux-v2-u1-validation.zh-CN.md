# UX v2.0 U1 验收记录

## 状态

**U1：入口与路由修复已完成。** 本机 Windows 源码版使用 Qt 主窗口验证，项目数据为脚本新建的合成空项目和一条合成路径；没有读取或修改用户项目。U1 阶段记录时 U0 的更广泛基线仍未完成，现已完成，见 [U0 报告](ux-v2-baseline.zh-CN.md)；U2–U7 当时未实施。

## 实现

- 新增 `src/gaussianreadpro/ui/project_actions.py`：共享 QAction 目录、严格 key 查询、可用性/原因状态，并将文本按钮与同一动作的文字和启用状态同步。
- `main_window.py` 将项目操作菜单、顶栏按钮、导入/计算快捷键和编辑器入口接到共享动作；只读状态会同步禁用 `Ctrl+I` 与新建路径动作。添加稳定 `activate_route(home|sources|path_nodes|energy)`，保留主堆栈既有页面索引。
- 能量页的路径节点/能量图/节点详情切换条移到能量图与节点编辑页共同可见的位置；源文件导航恢复可见。页面与尺寸变更统一由 `render_layout()` 管理，移除 `_sync_replica_shell`。
- 顶栏常驻项目名、保存状态、保存和“编辑反应路径”。在 840×680 窗口中收起次要品牌、搜索、新建/打开和页面标题，为主要控件保留宽度。
- 顶栏、路径编辑页和图表原生工具栏共用编辑器动作；无项目时会进入新建项目名称选择。图表“+”与“新建反应路径”会在完整 `ReactionBuilderDialog` 中初始化新路径草稿；无项目时也会保留“新建”意图。新草稿默认名称遵循当前界面语言。只读项目仍可打开查看现有路径，但外部与搭建器内部的新建动作均禁用。已有节点选择对话框保留为明确的“高级”入口。源列表导航命名为“计算日志”。
- 新增中英文动作翻译；没有改动项目重命名和科学/存储语义。

## 验证

使用仓库记录的 Windows 进程亲和性兼容运行器（仅限制验证进程及其子进程，未改系统设置）：

```powershell
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_workflow_actions.py tests\test_multi_paths.py -vv --basetemp=artifacts\ux-v2\u1\pytest-u1-final-20261018-09
```

结果：退出码 0，**11 passed in 18.26s**。覆盖入口可见性/可点击性、原生图表回退、稳定路由、无项目的新建选择、新路径草稿意图与只读禁用、动作 key/快捷键/可用性、共享按钮绑定，以及现有多路径行为。两次早期整组运行出现 Windows Qt 原生堆错误；定向组合及此最终完整命令通过，堆错误为间歇性且未能稳定复现。

真实 Qt 窗口检查：

```powershell
.venv\Scripts\python.exe tools\check_workflow_actions_u1.py
```

结果：退出码 0。Windows Qt 窗口尺寸 **840×680**，进程亲和性 `0xffffff3f`。脚本从顶栏可见按钮发送鼠标点击，实际打开 `ReactionBuilderDialog`；对话框活动路径 UUID 与当前活动路径一致。图表 WebEngine 在本机报告 renderer stopped，原生图表工具栏按钮仍显示且可用。运行目录：[`desktop-runs/4553f932e062487088642af58ddc4d63`](../artifacts/ux-v2/u1/desktop-runs/4553f932e062487088642af58ddc4d63/)。截图：

- [840×680 能量页入口](../artifacts/ux-v2/u1/desktop-runs/4553f932e062487088642af58ddc4d63/energy-entry-840x680.png)
- [实际打开的反应路径搭建器](../artifacts/ux-v2/u1/desktop-runs/4553f932e062487088642af58ddc4d63/reaction-builder.png)
- [机器可读桌面记录](../artifacts/ux-v2/u1/desktop-runs/4553f932e062487088642af58ddc4d63/u1-desktop-evidence.json)

## 边界

本阶段只恢复入口、路由与现有搭建器可达性。没有实现项目重命名、导入后作业选择、旧路径转换、画布编辑、应用/保存状态机或草稿保护。源码窗口在本机的 WebEngine 回退态检查了原生入口；冻结发行包、其他平台、DPI 矩阵和真实用户项目未验证。
