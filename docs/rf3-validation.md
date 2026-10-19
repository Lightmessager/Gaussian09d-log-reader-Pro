# RF3 Three.js 场景、相机与交互验收

2026-10-17：RF3 源码阶段完成。按用户要求先集中实现，再集中运行和调试；本轮止于 RF3。

## 实现

- 新增 `resources/plot/scene3d.js`，以本地 Three.js **0.170.0 / r170** 绘制 3D，提供 `mount/setData/setSelection/setViewport/resize/capture/dispose` 边界。2D 仍使用 Plotly；`GRPR_FORCE_PLOTLY` 保留明确的开发过渡入口，正式 WebGL 失败回退 2D 并持续显示原因。
- 固定正交默认相机，位置 `(6,-12,8)`、目标原点、Z 向上。共同场景尺度 X=12.4、Z=4.7，路径间隔 1.8。只转换显示坐标；各路径共用能量范围/变换，不单独缩放或平移能量。首次、重置、Fit 按数据范围适配；选点、语言和主题更新保留相机。
- 使用 Python `curve_runs`，不在 JS 重新插值或科学求值。屏幕空间宽线条带实现外光/内光/2.5px 线芯；节点 16px、选中核心 18px，选中橙白环及外晕保持屏幕尺寸。
- 每路径独立渐隐透明幕投到共同 `z_min`；地板与真实零能量平面分开。透明材质不写深度，幕对象原点移至自身中心以供随相机深度排序。装饰不参与节点命中；命中只检查真实节点的屏幕圆形区域，保持 UUID 身份与 Ctrl/Shift 追加选择协议。
- HTML 两行标签按候选位置避让、选中优先。230px tooltip 跟随实际投影，显示原始 DTO 的体系能量、显示值和全部来源；多来源可展开，作业序号来自确切 Job ID 映射。文本用 `textContent`。浅/深色均可读。
- 方向立方体使用主相机 quaternion 的逆变换实时绘制；面/轴可点击切换，独立接收鼠标。旋转/平移/缩放、滚轮、Fit、重置接通同一个场景。拖动阈值防止松开误选。
- `three_v1` 相机扩展经过 Python 白名单：版本、正交投影、有限 position/target/up、非退化方向和 zoom 范围。SQLite schema 仍为 v1。旧 Plotly eye/center 明确按共同场景半尺寸转换，up 保留方向并归一化；扩展缺省且无旧 camera 时使用新默认镜头。已保存相机菜单优先恢复 `three_v1`。
- 修复真实验证发现的状态竞争：项目快照将 JSON 数组冻结为 tuple，网页传回 list；控制器现在在比较前规范化双方，避免无变化的相机反复触发备份/修订、使用户点击信封失效。渲染调度只在实际不一致时回传相机。
- 离线文件及 MIT 许可位于 `resources/plot/vendor/`，版本/参数/大小/SHA-256 见 `three-manifest.json`。资源来源为 [Three.js 官方 r170](https://github.com/mrdoob/three.js/tree/r170)，相机采用 [官方正交相机](https://threejs.org/docs/pages/OrthographicCamera.html) 模型；运行期不访问网络。

## 真实源码窗口验证

主验收：`artifacts/rf3/validation.json`，**33/33 通过**，PID **48936**。程序实际启动当前源码，1672×941 DIP、DPR=1；截图为未修改的 `QWidget.grab()`，报告保存模块路径、PID、源码/资源和截图哈希。最后核对报告源码哈希与磁盘文件一致。

- Three.js 实际运行版本 170，8 个真实可选节点、2 个独立透明幕。
- 默认场景投影包围盒占图区宽 **90.0%**、高 **78.493%**；共同 Z 范围 **−20…20**，8 个节点标签无互相重叠。
- 真实 Qt 原生鼠标事件验证 B/I1 身份选点、旋转、反向观察、平移、拖动不误选、立方体 Z 轴点击；事件记录含 `isTrusted=true`。相机经受守卫的桥接事件保存。
- 新旧相机显式转换、新场景恢复、重置、2D/3D 切换、路径显隐和比较通过。缺值 DTO 的节点被排除且 Python 曲线分段保持断线。
- 强制不可用 WebGL 路径实际切到 Plotly 2D，提示持续存在；恢复 3D 后正常绘制。此降级检查不计作 3D 渲染通过证据。
- 同一 renderer 连续 **100** 次数据更新，第 1/50/100 次均为 **62 objects / 54 geometries / 9 textures / 11 listeners**。闲置不持续 RAF；隐藏 3D 后停止绘制。这里验证资源计数有界，不代表 GPU 显存或长期压力验收。
- 所有科学显示数值与输入 DTO 一致；PNG 捕获入口、全部来源 tooltip、本地依赖 SHA、中文浅色 1440×900 冒烟通过；JS 错误 **0**。

独立进程重启：`artifacts/rf3/restore-validation.json`，**3/3 通过**，新 PID **43772**。前一个进程显式保存非默认旋转镜头到 `.grproj` 并结束；新进程创建全新 Qt/WebEngine/Three 场景，从磁盘恢复的 position/target/up/zoom 与预期完全相等。另实际扰动镜头后调用“恢复已保存相机”菜单，再次恢复一致。不是只在同一 JS 对象里读回状态。

原始截图：

- [默认英文深色](../artifacts/rf3/rf3-en-dark-1672x941.png)
- [旋转透明层](../artifacts/rf3/rf3-rotated-transparency.png)、[背面透明层](../artifacts/rf3/rf3-back-transparency.png)、[顶部视图](../artifacts/rf3/rf3-top-view.png)
- [中文浅色](../artifacts/rf3/rf3-cn-light-1440x900.png)、[新进程恢复](../artifacts/rf3/rf3-fresh-process-restored.png)

## 命令与回归

```powershell
.venv\Scripts\python.exe tools/check_profile_scene3d.py
.venv\Scripts\python.exe tools/check_profile_scene3d.py --restore-only
.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'tools');from diagnose_static_runtime import windows_affinity;m,_,s=windows_affinity();s(m['default'] & 0xffffff3f);import pytest;raise SystemExit(pytest.main(['tests/test_workbench.py','tests/test_glass_preferences.py','tests/test_plot_spec_export.py','tests/test_plot_inspector.py','-q']))"
```

相关源码回归 **71 passed in 73.10s**。最后相机菜单接入后，Three 专项再测 **3 passed, 24 deselected in 1.05s**，并由新进程实际调用菜单通过。新增白名单/SQLite 往返、非有限/退化/非法版本拒绝、冻结数组不重复排队及新菜单选用 Three 状态的回归。

所有真实 Qt 验证继续使用已记录的进程级兼容掩码 `0xffffff3f`；未重开 G4 调度崩溃调查。这些结果仅覆盖本机 Windows 源码、DPR=1，不替代 RF7 高 DPI、长期性能、其他平台及发行包验收。

## 阶段边界

RF4 真实结构、完整详情/概览/表格仍为明确占位。RF5 完整 2D/响应式与高 DPI、RF6 完整导出/审计包和保存兼容矩阵、RF7 新 EXE 均未开始。当前 3D PNG 走新场景捕获；离线 HTML/静态审计导出仍沿用 Plotly 过渡路径，尚未宣称与新 3D 视觉一致。科学核心和来源身份规则未改变。
