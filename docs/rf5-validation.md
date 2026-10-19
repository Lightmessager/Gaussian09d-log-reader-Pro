# RF5 验收记录

## 范围

RF5 完成源码层的 2D/3D 操作、节点键盘访问、路径显隐与比较、选择状态保留，以及窄窗详情抽屉。二维图支持平移、框选缩放、键盘缩放和适配；三维图支持旋转、缩放与适配。隐藏路径后会清除其选中项；无兼容可见路径时比较功能禁用。可访问节点列表按当前有效节点生成，方向键/Home/End 浏览，Enter/Space 选择。窄窗详情可打开，Escape 关闭。

涉及 `resources/plot/profile.html`、`profile.js`、`replica_controls.js`、`replica.css`、`ui/profile_view.py`、`core/plot_spec.py`。PlotSpec 仅增加重叠路径节点标签错位，不改科学数据或计算。

## 验证

- `tools/check_profile_rf5.py` 在真实 Windows Qt/WebEngine 应用中集中执行 19 项检查；DPR=1 与 DPR=1.5 的报告均为 19/19、无 JavaScript 错误、单 WebEngine。覆盖模式切换及选中 UUID 保留、2D/3D 操作、键盘节点选择、路径与比较、空状态、中英文切换、窄窗抽屉/Escape。
- 相关回归：`tests/test_profile_rf4.py`、`tests/test_plot_inspector.py`、`tests/test_plot_spec_export.py`，40 passed。
- 静态检查：`node --check` 检查两个脚本；`python -m compileall -q src/gaussianreadpro tools/check_profile_rf5.py` 成功。
- Qt 进程使用已记录的 affinity 掩码 `0xffffff3f`，规避本机已知 G4 调度崩溃。DPR 环境分别为 `QT_SCALE_FACTOR=0.8` 与 `1.2`。

复现原生验收（在仓库根目录）：

```powershell
$env:QT_SCALE_FACTOR='0.8'
.venv\Scripts\python.exe tools\check_profile_rf5.py
$env:QT_SCALE_FACTOR='1.2'
.venv\Scripts\python.exe tools\check_profile_rf5.py
```

启动前按本机验收约定将进程 affinity 设为 `0xffffff3f`。报告： [DPR 1](../artifacts/rf5/validation-dpr1.json)、[DPR 1.5](../artifacts/rf5/validation-dpr1_5.json)。真实 Qt `QWidget.grab()` 截图：[DPR 1 标准画布](../artifacts/rf5/rf5-en-dark-1672x941-dpr1.png)、[DPR 1 窄窗抽屉](../artifacts/rf5/rf5-en-dark-840x680-drawer-dpr1.png)、[DPR 1.5 标准画布](../artifacts/rf5/rf5-en-dark-1672x941-dpr1_5.png)、[DPR 1.5 窄窗抽屉](../artifacts/rf5/rf5-en-dark-840x680-drawer-dpr1_5.png)。窄窗浏览器 CSS 视口为 796×630；DPR=1.5 时 Qt 窗口截图为 1290×1020。

## 边界

这是 Windows 源码验收；没有重建或验收发行 EXE，也没有验证 macOS/Linux。RF6 的完整离线导出与 renderer 迁移未开始，3D HTML 导出仍处于过渡实现；既有导出选择格式、语言及审计包流程不作为 RF6 完成的证据。RF6–RF8 仍未开始。
