# 当前交接：UX v2 U0–U8 与 Windows 2.0.0 包验收

2026-10-18 U8 最新：GaussianReaderPro 2.0.0 Windows x64 便携包已全量构建，包审计 10/10、默认首页新建/保存/改名/打开搭建器 7/7、Agg PNG/SVG/PDF 均通过。WebEngine 页面在源码与冻结版均未加载，未宣称 WebEngine/3D 通过。ZIP SHA256 d67ee20cdbc66f8e96dce3ebe70a8c9d177400dadef62f4ac90335811c132d00；EXE SHA256 e9fdc3e652835b92847d756130e7db1cee7f210eb3662ccdfbd9403192faa587。完整结果见 docs/ux-v2-u8-validation.zh-CN.md；无单进程仓库全量测试。

U7 历史交接（2026-10-18）：UX v2 U0 基线已完成并于 19:25 做只读复核；U1–U7 源码阶段及 U7 本机路线验收已完成。U0 冻结版/源码对照、三场景与保存边界证据见 `docs/ux-v2-baseline.zh-CN.md`。U1–U6 实现范围和阶段证据见 `docs/ux-v2-u1-validation.zh-CN.md` 至 `docs/ux-v2-u6-validation.zh-CN.md`。U7 修复了应用保存后草稿基线未刷新导致新建路径误报未应用草稿的问题；默认首页路线完成改名、导入与作业选择、双路径构建/零点/预检/保存、含硼结构、能量图、HTML 数据导出和新进程重开比对。三份固定真实 Gaussian16 日志完成 SHA/SCF 来源行验证和项目保存/新 SessionBackend 往返；三者相对能量相同，不能作为势垒证据。U7 桌面报告、回归命令/退出码、截图与实际限制见 `docs/ux-v2-u7-validation.zh-CN.md`；总体索引 `docs/ux-v2-validation.zh-CN.md`。本机 WebEngine 无法加载本地能量图页面，原生二维后备正常显示（U7当时状态）。后续 U8 已构建 2.0.0 包并完成 EXE 首页点击验收；WebEngine 源码与冻结版仍报 profile.html failed to load。包、哈希和证据见 docs/ux-v2-u8-validation.zh-CN.md。没有运行单进程仓库全量测试；无关底层故障排查未扩展。以下 S8 文字为历史记录，不代表 UX v2 当前状态。

2026-10-17：S8 新增同项目导入→Gibbs 参考计算→离线 HTML 审计→保存→新会话重开测试，独立通过；修复图表降级清除多路径比较选择，旧 S7 合成验收夹具补同作业 Gibbs 热校正。固定 cclib Gaussian16 三日志的核心性能样本见 `artifacts/s8/core-performance.json`。全测试按核心/界面/存储及单项四个进程分组 **348 passed, 1 skipped**；单进程长序列仍出现编辑器高度断言波动及 SQLite/Qt 原生中止。正常桌面权限下更新旧 S7 脚本至当前 Three.js 界面后，原生 **15/15** 通过并生成多主题截图；另以三份真实日志完成原生导入、显式 SCF 绑定、相对能量、绘图、HTML 导出、保存/新会话恢复，WebEngine 真实节点迹线和 UI 数值均通过。真实路径能量差为零，尚缺非零势垒样本。约 1000 行仍是 offscreen 合成表格，UI/WebEngine 内存与大文件负载证据未齐，故 S8 未过关。完整复现命令、数值和待办见 `docs/s8-validation.md`。下面 S7/G6/EP6 状态为历史基线。

2026-10-15：共享 PlotSpec、离线 Plotly 二维能级与三维分类路径、表格联动、视口/相机/标签恢复、显式局部势垒和正式导出已接入。全量 245 项测试与 Windows 原生 15 项验收通过。当时契约 v1.7，决定 D033–D037，证据见 docs/s7-validation.md 和 artifacts/s7/validation.json。

最新 EP6：用户 demo 指定的平滑高光曲线、圆形节点、橙色选中光环与 3D 光带/投影幕已完成（D038，当前契约 v1.8）。整高图表与独立节点表页签，放大视图共用详情；小概览、HTML 及静态导出同步。全量 273 passed；原生 7/7、60 张截图及每模式 100 次更新通过。报告 `docs/ep6-validation.md`，截图 `artifacts/ui-glass/ep6/final/`。保持科学节点与显示采样分离。下文 S7 数据为历史结果。S8/S9 需用户明确启动。

启动：.venv\Scripts\python.exe tools\run_app.py。安装：python -m pip install -e ".[dev]"，python tools/vendor_plotly.py。Windows 精确依赖为 requirements-s7-windows-lock.txt；PySide6 6.12.0、Matplotlib 3.11.2、本地 Plotly.js 4.1.1。

## 代码入口

- core/plot_spec.py：从当前 calculate_path 结果构建不可变 PlotSpec；统一单位投影、参考签名、标签避让、视图白名单与双点差值。JS 不计算科学值。
- services/session.py、controller.py：worker 返回 SessionView.plot_spec；视图与工作区约 400ms 合并修订。导出前重新核对来源指纹；忙碌时最新本机偏好排队，避免语言切换竞争。
- ui/profile_view.py：本地协议 2、project/revision/render_id 检查、只读临时视图、放大、导出与降级。MainWindow.preview 保留原生后备，MainWindow.profile 为正式面板。
- resources/plot/profile.html、profile.js：串行 Plotly.react、一次绑定、真实 scatter/scatter3d、文本转义、选择/图例/视口。本地 S0 页面保持独立。
- services/plot_export.py、static_plot_worker.py：新目录结果包、审计表/清单；二维由独立纯 Agg 进程渲染，三维 PNG 捕获当前 WebGL；HTML 携本地资源，离开 Qt 仍可用。

## 下一阶段 S8

先读 IMPLEMENTATION_PLAN.zh-CN.md 第 12 节及 S8、docs/contracts.md v1.8、docs/decisions.md。验证导入 → 构建公式/参考 → 比较 → 导出 → 保存/退出/恢复的完整用户流程；覆盖真实日志、快速变更、取消/过期任务、来源缺失/改变及保存失败。记录人工核对、复现步骤，修复后重跑相关验证。

继续测量解析吞吐、主线程响应、来源指纹开销、导出时间、连续更新内存/WebGL 资源及高 DPI。S7 的 100 次更新仅证明结构数量未累积；EP6 补充 UI/WebEngine 进程 private bytes 和工作集样本，GPU 显存、改版前可比基线及大文件仍待验证。

保持现有串行 SessionBackend、来源指纹覆盖、UUID 与科学求值语义。SQLite v1 不变。100 步撤销仅本会话，导入/重连清历史；复制路径共享节点，参考是独立表达式快照；构建器最多 40 行，复杂专家式不自动改写。无效草稿不可计算。二维拖动只改标签偏移，三维优先选中标签与悬浮；密集图可放大或隐藏路径。

## 执行与边界

原生验收：.venv\Scripts\python.exe tools\check_s7.py，会显示测试窗口并创建独立合成项目。Codex 受限进程不能可靠启动 WebEngine，需正常桌面执行权限；没有关闭 Chromium sandbox。历史 check_s4.py 显式测试原生概览；offscreen 回归不替代 WebGL 验收。

Windows 源码运行和本机 Windows x64 冻结便携包已验证；macOS/Linux 与其他 Windows 版本尚未实测。S0 演示包不是发行包。后续 S9 可在各目标平台分别验证 Agg 子进程入口、Matplotlib 数据/字体、生产 HTML/JS 和 WebEngine 资源。二维 PNG/SVG/PDF，三维 PNG/HTML；HTML 必须复制整个目录。结果包含来源路径与表达式，可在 sources.csv/plot.json 查看。


