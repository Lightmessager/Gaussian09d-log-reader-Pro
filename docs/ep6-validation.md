# EP6 与 demo 视觉对齐验收

2026-10-15。用户明确要求平滑高光线条、圆形数据点、橙色选中高亮和三维面积虚影；D038 覆盖早期水平能级方案。最终通过状态、原生报告及性能数据见下文运行记录。

## 实现与科学边界

- `core/plot_spec.py` 生成共用的显示曲线几何；连续有效节点之间使用 smoothstep，经过真实节点、不超出相邻端点值域，遇到缺失/无效节点断开。计算、CSV、势垒及来源追溯仍只使用真实节点。
- `resources/plot/profile.js` 绘制多层高光曲线、圆形节点光晕、橙色选中双圈和投影线。3D 添加沿曲线的半透明光带、到零面的低透明度投影幕；装饰层跳过 hover/选点，不连接不同路径生成势能面。颜色沿用薰衣草紫与落日橙。
- `ui/main_window.py`、`profile_view.py` 默认整高图表，节点表单独页签；可见 2D/3D 分段按钮。宽窗展示只读详情，窄窗用独立详情页签；放大窗口复用同一浏览器及详情组件，支持收起详情。
- `plot_inspector.py`、`profile_preview.py` 统一选中值、来源与小概览。`services/plot_export.py` 的静态图也使用相同显示几何；白底论文输出与屏幕深色主题分别保留。
- 原生拖动结束后读取 WebGL 场景真实相机，通过既有白名单事件保存。刷新保留现场相机，消除视图修订期间旧事件被拒绝造成的回跳，并抑制浮点误差引起的重复保存。
- PlotSpec 科学求值、SQLite v1、事件协议 2 和来源验证语义不变。图中明确说明曲线/光带仅作视觉引导。没有新增示意图中的虚构分子结构或未实现模块。

## 检查方法

全量回归命令：

```powershell
.venv\Scripts\python.exe tools\run_pytest_compat_windows.py -q --junitxml=artifacts/ui-glass/ep6/full-pytest.xml
node --check src/gaussianreadpro/resources/plot/profile.js
.venv\Scripts\python.exe -m compileall -q src tools/check_energy_profile_ep3.py tools/check_energy_profile_ep5.py tools/check_energy_profile_ep6.py tools/check_energy_profile_suite.py
.venv\Scripts\python.exe tools\check_energy_profile_suite.py
```

pytest：273 passed，68.29s；JUnit 为 273 tests、0 failures、0 errors、0 skipped。JS 语法与 Python 编译检查通过。CN/EN 两份语言文件各 359 个键且完全对应。

原生套件依次运行 EP2、EP3、EP4、EP5 和 EP6 DPR 1/1.5/2。三档 DPR 是本机 125% 桌面下以进程 `QT_SCALE_FACTOR=.8/1.2/1.6` 得到的 Qt DPR，不能代替三台物理显示器验证。每档包含 CN/EN × light/dark × 1440×1000/860×680 × 2D/3D 的 16 张 Qt 截图，另有 4 张代表性/展开截图，共 60 张。

EP6 使用原生鼠标点击 2D I1/TS1，核查光晕层没有挡住真实节点，并实际拖动 WebGL 场景，核对真实相机与保存值。EP3 的 3D 节点 ID 往返检查通过注入 Plotly click 事件完成，不能称为真实 WebGL 节点鼠标命中测试。

EP5 验证 2D PNG/SVG/PDF/HTML、3D PNG/HTML，清单 SHA-256、来源变化拒绝、目标目录保护、只读会话与重开恢复。SVG 用 QtSvg、中文 PDF 用 QtPdf 实际渲染后检查；两个离线 HTML 均从本地资源成功绘图。

## 修复与失败记录

历史运行保留原始报告。复验中修复了实际场景相机与 Plotly layout 相机不同步、刷新竞争及重复浮点事件；脚本改用真实相机预设，避免手动注入保存状态覆盖现场。真实点击前等待一次 Plotly hover 命中更新，消除脚本在移动后立即点击得到旧悬浮节点的问题。

DPR 2 的窄窗截图曾出现多路径标签重叠/裁切，现优先显示活动路径及选中节点，其余通过 hover 查看；去除 Qt 图表内与路径菜单重复的图例。另一次 EP3 保存检查错误地取字典中第一条路径的相机，现按活动 `context/3d` 精确读取；保留原始失败报告 `artifacts/ui-glass/ep6/suite-5e9912c93ca64d2292c1245edfb4d1bb/`。

## 验证范围

Windows 源码、正常桌面权限下运行真实 Qt/WebEngine/WebGL。全部 Qt 验收使用进程级亲和性 `0xffffff3f`，没有修改系统设置或禁用 Chromium sandbox；G4 默认调度崩溃仍未关闭，遵守用户要求暂不继续底层排查。

性能为合成三路径、四节点、预热后每种模式 100 次选择更新，记录真实 trace 数和 Plotly emitter 的五类监听器数量。Windows Toolhelp32 枚举 UI 及其 WebEngine 子进程，GetProcessMemoryInfo 记录工作集/private bytes；GPU/驱动显存未覆盖。没有改版前可比基线，有限样本不能证明无内存泄漏，也不代表帧率或大型项目性能。macOS/Linux、正式安装包、跨平台导出打开和大规模真实日志压力仍未验证。没有进入 S8/S9。


## 最终运行记录

最终套件 **7/7 通过**，`source_unchanged_during_suite=true`；报告记录 9 个产品源文件的 SHA-256。

| 检查 | 原始报告 | 结果 |
| --- | --- | --- |
| ep2 | [`validation.json`](../artifacts/ui-glass/ep2/78b3354d2d694e7a8afa886bc2339c75/validation.json) | passed |
| ep3 | [`validation.json`](../artifacts/ui-glass/ep3/66e4c02417784c5885a0a30ce04d0dff/validation.json) | passed |
| ep4 | [`validation.json`](../artifacts/ui-glass/ep4/cdd70034bc1c4622bc2e2630873640b0/validation.json) | passed |
| ep5 | [`validation.json`](../artifacts/ui-glass/ep5/b27be56d2565417ea763ede7487d143e/validation.json) | passed |
| ep6-dpr1 | [`validation.json`](../artifacts/ui-glass/ep6/3d2ffc50fe66468f8babfa4258c73495/validation.json) | passed |
| ep6-dpr1.5 | [`validation.json`](../artifacts/ui-glass/ep6/9159300e09fd4255a121c3382ccc9ee0/validation.json) | passed |
| ep6-dpr2 | [`validation.json`](../artifacts/ui-glass/ep6/1f34e4ed0481478990ff54bf3540b290/validation.json) | passed |

总报告：[suite validation](../artifacts/ui-glass/ep6/suite-8f82c87c0e1b425cb6709b3651b9de50/validation.json)。便捷副本与原始路径映射：[final/sources.json](../artifacts/ui-glass/ep6/final/sources.json)。

人工检查：最终 2D/3D 工作区、放大 3D、DPR 2 窄窗 2D 与 DPR 1.5 窄窗 3D；中文 PDF 与 SVG 实际渲染预览。代表截图：[2D](../artifacts/ui-glass/ep6/final/2d-workbench.png)、[3D](../artifacts/ui-glass/ep6/final/3d-workbench.png)、[放大 3D](../artifacts/ui-glass/ep6/final/3d-expanded.png)。

环境：Windows 11 / Python 3.12.14 / Qt 6.12.0 / process affinity `0xffffff3f`。

| 模式 | 100 次耗时 | 单次中位 / P95 | trace | UI private MiB 起→末 | WebEngine private MiB 起→末 |
| --- | --- | --- | --- | --- | --- |
| 2D | 4.685s | 45.23 / 56.11ms | 21 | 686.66→522.76 | 240.84→242.21 |
| 3D | 4.730s | 45.58 / 56.94ms | 34 | 733.81→734.92 | 242.25→244.39 |

两种模式 render count 均恰好增加 100；五类实际 emitter 监听器各保持 1 个。每 20 次更新的完整内存样本、各进程 PID/工作集与相机事件见原始 DPR 1 报告。本样本没有呈现随更新次数线性增长的图层/监听器；内存起末值不能作为长期泄漏结论。
