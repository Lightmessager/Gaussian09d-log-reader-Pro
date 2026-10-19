# L5 集成复核记录（2026-10-17）

状态：**自动化集成复核通过；项目书要求的桌面交互与截图验收受环境阻塞，L5 暂未完全关闭。**

## 已验证链路

本阶段以项目书现有的受控合成 Gaussian 夹具和应用服务/Qt 工作台用例为证据，不将合成数据表述为真实化学来源。

- `tests/test_reaction_network.py`：**13 passed**。覆盖同作业 SCF + Gibbs 热校正、整条路径阶段/零点计算、零点平移、路径保存重开、递推账本、工作簿公式回归、分支路径、边级配平/确认、关系网快速部署预览、星标进入图表数据。
- `tests/test_workbench.py`：**29 passed**。覆盖导入、具名项目保存、重命名、Recent 移除与单独项目删除、失败打开/保存等生命周期行为；语言/主题切换后检查所选节点、科学值和工作区状态保持。
- `tests/test_multi_paths.py`：**3 passed**。覆盖多路径创建、颜色和参考继承、保存后恢复。
- 合计独立进程结果：**45 passed**。

实际命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_reaction_network.py -q
.venv\Scripts\python.exe -m pytest tests/test_workbench.py -q
.venv\Scripts\python.exe -m pytest tests/test_multi_paths.py -q
```

三条命令分别以退出码 0 完成。将三文件合并到一个进程运行时，进程在 `test_project_rename_delete_and_recent_removal_are_scoped` 的后台 SQLite 保存/回收等待处由 Python 原生 `Fatal Python error: Aborted` 终止；工作台文件单独运行完整通过。这个合跑稳定性问题不算通过，也不能据现有栈确定为 L5 新改动造成。

## 未完成项与阻塞

项目书 L5 还要求用一个含 B 元素的数据在同一窗口内连续完成完整反应式、两条关系网部署路径、搭建器加星、图上右键核查、保存/退出/新进程重开、主题切换，并集中记录窗口尺寸、DPR 和截图。现有自动化覆盖上述功能的多个真实入口和持久化环节，但没有形成一条在可见桌面中完整连续操作的录屏/截图证据，也没有可访问桌面证明 DPR 与窗口尺寸。

本轮调用 CUA 桌面状态只返回空的 `apps` 列表和无任务标签页的浏览器列表；没有可由 CUA 操作的应用窗口。当时的受限命令环境也未能加载 WebEngine。随后 S8 已证明正常桌面权限下原生 Qt 脚本能产生实际窗口截图（见 `docs/s8-validation.md`）；因此这里的阻塞应精确表述为 **CUA 不可见与 L5 指定的含 B 连续桌面验收尚未执行**，不能再概括为本机完全没有桌面窗口。未把离线 Qt 测试冒充 L5 桌面验收。

## 结论

可复核的自动化集成覆盖通过，剩余阻塞是桌面交互证据和合跑原生中止的复现/定位。L5 待在能访问应用窗口的桌面环境中执行项目书集中验收，并在独立 pytest 进程环境下进一步调查合跑异常后再关闭。
