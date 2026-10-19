# RF6 状态恢复与离线导出验收

2026-10-17：RF6 源码阶段完成。Windows 真实 Qt/WebEngine 集中验收 **31/31**；相关回归 **45 passed**。最终原生报告为 [validation.json](../artifacts/rf6/validation.json)，实际进程 PID 为 2492、42468；完整运行目录为 `artifacts/rf6/run-b4f4796126/`。RF7/RF8、S8/S9 未开始，Windows EXE 未重建。

## 实现范围

- 项目视图白名单增加选中点 ID、详情显示/窄窗抽屉状态，保留 2D 范围和 `three_v1` 相机各自的上下文。新字段走现有串行工作区保存链，SQLite v1 不变；旧 Plotly 相机通过已有显式转换恢复到 Three。只读项目的视图修改仅留在面板临时状态。
- 3D 图表 PNG 使用 `ProfileRenderer.capture`，固定 1600×1000，按当前视口等比留边，保留当前相机、选择与导出语言；不切回旧 Plotly 3D。导出等待匹配的 render_id，捕获期间冻结输入，捕获回传实际视口，失败/超时恢复控件。
- 菜单明确区分“仅图表 PNG”和“工作台展示图 PNG”。后者为实际 WebEngine QWidget 捕获，包含工具栏、当前详情和分子；最终样例为 1476×891。二维论文 PNG/SVG/PDF 继续通过独立 Agg helper 生成白底图，并保留二维范围与审计数据。
- 离线 HTML 使用新的 Three 场景及同页详情、分子、方向立方体和工具栏。复制 Plotly、Three 原始资源、许可与 manifest；通过共享的 data: 模块 URL 加载 Three 依赖，避免 file:// ES 模块的文件源限制，不需要 Qt bridge 或本地服务器。CSP 禁止远程连接。
- 离线比较与路径切换消费 Python 预计算 DTO；不在 JS 重算科学数值。导出时会核验并将所有离线可揭示路径写入 `data.csv`、`sources.csv`，包括初始单路径显示之外的兼容路径；这些路径同样接受来源失效校验。
- 分子只嵌入当前选中且已通过 SHA/作业范围核验的坐标；不依赖本机缓存文件。其他节点显示“此节点未嵌入坐标”，不会沿用旧模型。原始日志不随 HTML 打包，依赖桌面项目/原始日志的编辑、定位与重新选择结构功能明确禁用。审计表仍保留来源路径、行号、SHA 和表达式。

主要代码：`core/plot_spec.py`、`ui/profile_view.py`、`services/plot_export.py`、`resources/plot/profile.js`、`scene3d.js`、`replica_controls.js`、`inspector_view.js` 与英文 locale；新增 `tests/test_profile_rf6.py`、`tools/check_profile_rf6.py`。

## 实际验证与产物

[写入/导出进程报告](../artifacts/rf6/run-b4f4796126/write-validation.json) 共 13 项：已核验分子、Three PNG 尺寸/相机/独立导出语言、工作台 PNG、资源/许可、坐标嵌入、三个结果包 SHA、同目录导出失败不覆盖、真实 QTimer 捕获超时恢复，以及项目文件落盘状态。

[独立重启/离线报告](../artifacts/rf6/run-b4f4796126/restore-validation.json) 共 18 项：新进程恢复状态/相机/选择/详情与独立 2D 范围、二维白底；移动整个 HTML 目录后从 file:// 打开，新 Three r170 与分子实际运行，无 Qt bridge；2D/3D 切换保留镜头、Compare 关闭后可重开并恢复双路径、换节点不显示旧分子、旧相机实际迁移、WebGL 不可用时明确降级到 2D，以及无远程请求/JS 错误。

最终导出样例：

- [当前相机 3D 图表 PNG](../artifacts/rf6/run-b4f4796126/chart-3d/profile.png)，1600×1000，中文导出；图表以当前非默认缩放与裁切为准，不为导出改动相机。
- [真实工作台展示 PNG](../artifacts/rf6/run-b4f4796126/workbench/profile.png)，1476×891，英文、深色、已选中 A/TS1。该文件是未经拼接的 QWidget 捕获。
- [离线 HTML](../artifacts/rf6/run-b4f4796126/offline-3d/profile.html)；分享时复制整个 `offline-3d` 文件夹。
- [移动后的离线副本](../artifacts/rf6/run-b4f4796126/relocated/offline-3d/profile.html)、[旧相机离线样例](../artifacts/rf6/run-b4f4796126/offline-legacy/profile.html)、[2D 白底 PNG](../artifacts/rf6/run-b4f4796126/paper-2d/profile.png)。

每个结果包包含 `plot.json/data.csv/sources.csv/manifest.json`；manifest 记录实际 raster 来源、尺寸、资源许可/哈希，发布失败清理新目录，已有目录不覆盖。主验收报告另记录源码与运行资源 SHA。保留了开发过程中发现离线 Compare 状态遗漏的失败记录 `run-8efd25ecb6`；最终判定只使用上述成功运行，不用旧阶段结果代替。

## 复现

原生验收程序会创建隔离项目、启动两个独立应用进程、生成所需导出，再运行离线页；不逐项截图。它自动应用本机既有亲和性掩码 `0xffffff3f`，`QT_SCALE_FACTOR=0.8`，本轮 DPR=1；没有禁用 Chromium sandbox。

```powershell
.venv\Scripts\python.exe tools\check_profile_rf6.py
```

自动回归命令（本机 Qt 同样使用已记录的进程亲和性）：

```powershell
.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'tools');from diagnose_static_runtime import windows_affinity;m,_,s=windows_affinity();s(m['default'] & 0xffffff3f);import pytest;raise SystemExit(pytest.main(['tests/test_profile_rf6.py','tests/test_profile_rf4.py','tests/test_plot_spec_export.py','tests/test_plot_inspector.py','-q']))"
```

结果：45 passed in 22.11s。覆盖新旧视图白名单/SQLite 往返、只读临时视图、离线可揭示路径的审计和来源失效校验、PNG 来源与尺寸、恶意标签转义、缺值、原子失败清理及 RF4/详情回归。`compileall` 和三个修改的经典 JS 脚本 `node --check` 通过。

## 边界

这是 Windows 源码验证，不是发行包验收；默认 CPU 调度、macOS/Linux、独立 Chrome/Edge/Firefox 尚未实测。离线页是在实际 Chromium QtWebEngine 中以普通 file:// 文档运行、无 QWebChannel、拦截远程请求验证。RF7 才进行最终视觉/性能和当前 Windows EXE 验收。合成夹具始终标记合成，不代表所有 Gaussian 版本兼容。
