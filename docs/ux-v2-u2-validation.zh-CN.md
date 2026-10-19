# UX v2.0 U2 验收记录

## 状态与范围

**U2：项目名、最近项目与保存反馈已完成。** 本轮依据用户指示只实施 U2，并按用户批准的窄窗口方案，在窗口高度低于 760 px 时将“继续研究”卡片移到首页首位；高窗口保留原来的信息顺序。U2 阶段记录当时 U0 基线仍未完成（现已完成，见 `docs/ux-v2-baseline.zh-CN.md`）；U3–U7 当时未启动。

本机桌面验证运行在 Windows，窗口尺寸为 **840×680**。验证脚本创建的项目、日志和目录均为合成夹具，只写入 `artifacts/ux-v2/u2/desktop-runs/`；没有打开或修改用户项目。本轮未调用 Desktop Commander Remote MCP。

## 实现

- 当前项目名可点击并安全重命名。未保存项目的名称写入 `workspace_state["ux_v2"]["pending_project_name"]`；校验拒绝非法 Windows 文件名、保留设备名和不支持的仅大小写改名。
- 保存完成事件包含任务 token、项目身份、目标修订与目标路径。首次另存为只在身份匹配且目标修订确认保存后清除暂存名；取消、失败或提交拒绝保留名称与项目工作。
- 主项目文件保存反馈与恢复副本反馈分开；只读状态显示“只读”。
- 首页最近项目提供打开、重命名、从最近移除和删除项目文件按钮，并保留右键菜单快捷操作。
- 窗口高度低于 760 px 时，“继续研究”置顶；其他高度维持原有顺序。窄宽窗口内最近项目按钮排为两列，英文长标签不会截断。可见性回归检查五个按钮中心确实落在首页滚动视口内，并检查放大窗口会恢复原顺序。

## 自动化验证

命令：

```powershell
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_project_management_ux.py -q
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_workbench.py -q -k "not compact_reaction_view_switches_between_full_height_chart_and_nodes"
```

结果：U2 项目管理用例 **49 passed**，包含首次保存期间切换页面的竞态回归：保存成功后临时名不再进入工作区、主项目或恢复副本，且新页面状态保留。工作台回归子集 **28 passed, 1 deselected**。完整工作台曾发现一个现有紧凑反应页签断言与 `render_layout()` 的可见规则不一致；该路由不属于 U2，本轮未修改该行为，故从 U2 相关回归子集中排除。

## 本机 Qt 桌面验证

命令：

```powershell
.venv\Scripts\python.exe tools\check_project_management_u2.py
```

结果：退出码 0，Windows Qt 窗口 **840×680**。桌面脚本记录：

- 首次保存取消后暂存名保留；保存失败后暂存名保留；重试后保存成功并从活动项目移除暂存名。
- 当前项目改名成功后旧文件移除、新文件存在、当前路径更新，项目 UUID 保持不变。
- 非当前最近项目改名成功后最近列表更新，当前项目保持不变。
- 中文界面下最近项目的打开、重命名、移除、删除和继续工作五个按钮均可见、启用、可键盘聚焦，且位于滚动视口；英文完整标签和启用状态也全部正确。

机器记录：[u2-desktop-evidence.json](../artifacts/ux-v2/u2/desktop-runs/fdc62e16518c407d96163874fed41512/u2-desktop-evidence.json)

截图：

- [840×680 中文首页最近项目操作](../artifacts/ux-v2/u2/desktop-runs/fdc62e16518c407d96163874fed41512/recent-project-actions-840x680.png)
- [840×680 英文首页最近项目操作](../artifacts/ux-v2/u2/desktop-runs/fdc62e16518c407d96163874fed41512/recent-project-actions-en-840x680.png)
- [首次保存失败后的名称保护](../artifacts/ux-v2/u2/desktop-runs/fdc62e16518c407d96163874fed41512/first-save-failed-840x680.png)

## 边界

验证使用本机源码和合成项目；没有覆盖冻结发行包、其他 DPI/操作系统或用户真实项目。U0 全面行为基线当时仍未完成，现已完成并见 `docs/ux-v2-baseline.zh-CN.md`；S8 综合验收仍未完成，U3–U7 当时尚未实施。
