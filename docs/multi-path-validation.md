# 多反应路径与自定义颜色

2026-10-17：按用户追加要求，新增能量页路径创建入口与多路径管理。属于 RF6 后的功能追加，没有开始 RF7 或重建 Windows EXE。

## 使用

1. 能量页顶部路径区点击 **+**，填写路径名称、选择颜色或输入 `#RRGGBB`。
2. 可勾选项目已有节点，并拖动调整其在新路径中的顺序。它们是明确的共享节点，编辑表达式会影响使用同一节点的路径；也可不勾选，创建空路径后从“路径节点与编辑”添加独立节点。
3. 点击“创建并比较”。新路径继承当前活动路径的能量类型、单位和参考快照，自动成为活动路径并开启比较。空路径不伪造能量，没有有效节点时不生成曲线。
4. 两条路径时可直接使用顶部开关；点击 `···` 打开列表。三条及以上显示“路径 / Paths · 可见数/总数”，点击展开完整列表。每行支持显隐、设为活动路径，以及点击颜色值重新选色，修改非活动路径颜色不会切走活动路径。

比较不限于两条。沿用科学核心的类型/模式筛选、单位统一与参考签名检查；不同参考仍显示各自零点的警告，不自动改变参考或计算不成立的跨路径差值。新条目使用独立 entry UUID，不按同名节点推断配对。

## 渲染与保存

每条路径复用现有 Three 曲线高光、节点和面积阴影，颜色来自该路径，透明衰减仍为原 shader 的 `.14*a*a`。路径数量改变时重新计算默认构图尺度，再恢复当前相机视口，避免新增路径超出旧深度画幅。二维主图、概览、关键能量表及离线导出使用同一数据和颜色。

概览图例不再只取前四条；多路径图例可换行/滚动，能量表按列数保留最小可读宽度并允许水平滚动。名称、颜色、节点顺序、活动路径和比较状态走现有项目保存链。创建与改色支持现有撤销/重做；只读或后台忙碌时不能修改路径。离线页可切换活动路径、显隐与比较，创建/改色须回桌面项目执行。

主要改动：`services/controller.py`、新建 `ui/path_editor.py`、`ui/main_window.py`、`ui/profile_view.py`、能量页 HTML/CSS/controls/inspector/Three adapter 及英文文案。

## 实际验证

最终报告：[22 项原生验收](../artifacts/multi-paths/validation.json)。运行目录 `artifacts/multi-paths/run-cd9ccdb637/`，写入进程 PID 50840，独立重启进程 PID 45628。

- [写入与真实弹窗操作](../artifacts/multi-paths/run-cd9ccdb637/write-validation.json)：13 项通过，包括“+”打开真实 Qt 创建对话框、点击勾选节点/创建、自定义颜色、新路径参考/节点身份、相同 shader、三路径列表与显隐、非活动路径改色、五条路径/20 个节点/五个阴影、五条图例与表格列、二维五路径和磁盘保存。
- [新进程恢复与离线运行](../artifacts/multi-paths/run-cd9ccdb637/restore-validation.json)：9 项通过，包括五条路径与颜色恢复、五个阴影、离线五路径、比较关闭再打开恢复五条、活动路径切换、离线修改按钮禁用，以及 JS 错误/远程请求均为 0。
- [最终真实截图](../artifacts/multi-paths/run-cd9ccdb637/five-paths.png)：1672×941，未经拼接的 QWidget.grab；只在最终状态截图一次。截图打开路径列表，展示五条路径的开关和自定义颜色。
- [五路径离线 HTML](../artifacts/multi-paths/run-cd9ccdb637/offline/profile.html)，分享须复制整个 `offline` 文件夹。

夹具为标记合成的 RF4 示例；C/E 明确选择 B 的已有节点，D 选择 A 的已有节点，因此部分路径具有相同能量。测试不将它们描述为五组独立 Gaussian 计算，也没有为区分曲线人为偏移能量。

相关回归 **48 passed in 40.33s**：`tests/test_multi_paths.py`、`test_profile_rf6.py`、`test_plot_spec_export.py`、`test_profile_rf4.py`、`test_plot_inspector.py`。新增测试覆盖颜色校验、节点顺序/ID、参考继承、保存、撤销重做、只读保护与非活动路径改色。`compileall` 与修改的三个经典 JS 脚本 `node --check` 通过。

复现原生验证：

```powershell
.venv\Scripts\python.exe tools\check_multi_paths.py
```

脚本自动使用本机已记录的 `0xffffff3f` 进程亲和性与 DPR=1，启动两个独立源码应用进程；没有禁用 Chromium sandbox。验证使用真实 Qt 颜色对话框。尚未测试大量路径的性能、其他操作系统或新发行 EXE。
