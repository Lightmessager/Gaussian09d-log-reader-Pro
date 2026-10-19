# RF7：GaussianReaderPro 0.2.0 Windows 包验收

日期：2026-10-17。范围为能量工作台 RF7 与用户指定的产品名/版本；不启动 RF8 或原总计划 S8/S9，不发布远端 Release。

## 变更

- 产品显示名、窗口标题、Qt 应用标识、命令行版本、导出元数据、Python 分发名和 Windows PE 产品信息统一为 **GaussianReaderPro 0.2.0**。
- 内部 Python 包仍为 `gaussianreadpro`，旧命令行入口保留；旧 QSettings 命名空间与恢复目录保留，避免改名后丢失本机设置/恢复工作。SQLite v1、UUID 和科学计算不变。
- 标准主图标签调整为 16/17 DIP、轴标签 14 DIP；导出捕获读取实际 DOM 字体/边界与旋转轴标题，保持当前 Three 场景；tooltip 按实际宽度布局。
- 窗口最低 840×680；表达式页脚长路径换行，保存/取消按钮不被挤出。补齐此前多路径/导出功能遗漏的 9 项中文语言键。
- 末尾人工检查发现 1100 宽度工具条文字越界与方向立方体/底栏重叠，修正中等窗口的控件最小宽度、横向滚动及立方体位置；tooltip 避让范围增加轴文字。离线 DOM 验收补查按钮文字是否在边界内、滚动是否可用、立方体与工具条分离、提示卡是否避开能量轴标题。
- 新 Windows 包包含 RF1–RF6 与多路径自定义颜色功能，沿用用户图标。补齐冻结 SVG/PDF 后端；静态渲染子进程异常通过结构化结果返回，防止窗口化 PyInstaller 的异常弹窗阻塞导出。

## 运行方式与产物

- [Windows 便携 ZIP](../artifacts/releases/GaussianReaderPro-0.2.0-Windows-x64-portable.zip)：解压完整目录，不单独移动 EXE。
- [本机兼容启动器](../dist/GaussianReaderPro/Launch-GaussianReaderPro-compat.cmd)。本机验证均使用进程亲和性 `0xffffff3f`，不改系统设置，不重查既有 G4 问题。
- 实际 EXE：`D:\Project\GaussianReadPro\dist\GaussianReaderPro\GaussianReaderPro.exe`。
- [构建清单](../dist/GaussianReaderPro/build-manifest.json)、[ZIP SHA256](../artifacts/releases/GaussianReaderPro-0.2.0-Windows-x64-portable.zip.sha256)、[包审计](../artifacts/rf7/bundle-audit.json)。旧包保留；没有覆盖远端文件。

## 验证方法

源码由生产 `tools/run_app.py` 启动；冻结验证直接执行指定新 EXE 的内部 `--validate-rf7` 入口，实际创建 MainWindow、ProjectController、QWebEngine 与 Three r170。测试不是另写的静态示意页。截图为未修改的 QWidget.grab，报告含 PID、程序路径、EXE/截图/资源 SHA、实际 DPR、WebGL 设备与操作坐标。

主链覆盖默认相机、真实鼠标旋转/平移/选点、详情与结构、路径显隐、100 次场景更新、2D/3D 和双语切换、六类实际导出、编辑后显式保存、注入保存失败后的草稿保留与重试、磁盘最终表达式核对。独立新进程再核对表达式、完整 plot_state 与 Three 相机。窗口矩阵覆盖 CN/light 1440×900、EN/dark 1100×820、冻结 DPR1.5 与 840×680/DPR2，包含窄窗详情抽屉。

双路径夹具明确标注合成例；通过正式计算链核对 A `[0,15.060,-5.020,-15.688]`、B `[0,11.420,-2.800,-12.400] kcal/mol`，分子坐标来自已验证来源作业。最后表达式含两次 `+0.000001` 是保存失败/重试用例的真实输入；默认截图和导出在编辑之前完成。

离线检查复制 **EXE 实际导出的整个 HTML 文件夹** 到新目录，在独立无 Qt bridge 的 QWebEngine 页面通过 file:// 打开，拦截远程请求；检查实际 Three、嵌入分子、2D/3D、相机与 Compare 往返。该离线宿主是源码 Qt，内容与资源来自 EXE 导出。

## 最终结果

**RF7 已完成（Windows 本机兼容配置）。** 全量回归 **306 passed**，1 项非功能性 pytest cache 权限警告；源码/EXE 主链、独立恢复与窗口矩阵全部通过。

| 运行 | 通过检查 | 实际拖动 FPS | 选择 p50/p95（ms） | 详情 p50/p95（ms） |
| --- | --- | --- | --- | --- |
| 源码 | 27/27 | 58.82 | 26.7/48.2 | 62.7/71.2 |
| 冻结 EXE | 27/27 | 52.89 | 23.8/33.5 | 58.6/75.7 |

独立新进程恢复与窗口矩阵 **43/43**；当前 EXE 导出文件搬移后的离线页 **11/11**；包审计 **9/9**、源码与包内 **36 个资源**逐字节 SHA 一致。冻结 PNG/SVG/PDF、CLI 和 WebEngine 握手烟测通过，见 `artifacts/rf7/windows-smoke.log`。

| 独立运行 | 检查数 | 证据目录 |
| --- | --- | --- |
| source / restore | 7 | `D:\Project\GaussianReadPro\artifacts\rf7\source-restore-default-36104d52` |
| frozen / restore | 7 | `D:\Project\GaussianReadPro\artifacts\rf7\frozen-restore-default-3355deec` |
| source / matrix | 7 | `D:\Project\GaussianReadPro\artifacts\rf7\source-matrix-cn-light-1440-496c5d71` |
| source / matrix | 7 | `D:\Project\GaussianReadPro\artifacts\rf7\source-matrix-en-mid-1100-1a8d1171` |
| frozen / matrix | 7 | `D:\Project\GaussianReadPro\artifacts\rf7\frozen-matrix-en-dpr1_5-2dd9785d` |
| frozen / matrix | 8 | `D:\Project\GaussianReadPro\artifacts\rf7\frozen-matrix-cn-narrow-dpr2-b164cac2` |

实际图形设备：`ANGLE (NVIDIA, NVIDIA GeForce RTX 4050 Laptop GPU (0x000028E1) Direct3D11 vs_5_0 ps_5_0, D3D11)`；Qt `6.12.0`，Python `3.12.14`。基准截图内容区 1672×941 DIP、DPR1；两路径图体宽/高占用 90.0%/78.5%；宏观边界最大误差 0.0 DIP。

| 深色文字/标记 | 对画布对比度 | 对面板对比度 |
| --- | --- | --- |
| text | 16.713:1 | 15.441:1 |
| muted | 9.91:1 | 9.156:1 |
| axis | 10.558:1 | 9.755:1 |
| path_a | 6.89:1 | 6.366:1 |
| path_b | 10.283:1 | 9.5:1 |
| focus | 9.332:1 | 8.622:1 |

以上按标准 token 与实际面板背景中位色计算；标准深色达到 4.5:1。自定义路径颜色由用户选择，不保证任意颜色的对比度。四处安静背景 RGB 单通道最大误差依次为 1、1、3、4（目标 ≤8）。

内存采样（MiB；预热/末次/峰值）：

| 运行 | UI private | WebEngine private |
| --- | --- | --- |
| 源码 | 497.3/498.7/505.8 | 211.8/217.5/217.5 |
| EXE | 503.1/509.1/509.1 | 219.6/224.6/224.6 |

实际截图绝对路径（其余操作/编辑截图见各运行 `validation.json`）：

- 源码默认：`D:\Project\GaussianReadPro\artifacts\rf7\source-primary-default-ce803a7d\default-3d.png`。
- EXE 默认：`D:\Project\GaussianReadPro\artifacts\rf7\frozen-primary-default-24ae6620\default-3d.png`。
- [EXE 实际默认截图](D:/Project/GaussianReadPro/artifacts/rf7/frozen-primary-default-24ae6620/default-3d.png)。

发行物标识：

- EXE SHA256：`4889b26df64fa8b1db4c1d6755b3ddab59fb8a97b102abfef5994e168ad8478d`。
- ZIP：284,049,513 bytes；SHA256：`22aefba7039ac643c56d9d5051f5e2e3afd31fe88f22b485a85df3d5fc9f591a`。

[综合原始报告](../artifacts/rf7/validation.json)、[源码摘要](../artifacts/rf7/source-primary-latest.json)、[EXE 摘要](../artifacts/rf7/frozen-primary-latest.json)、[矩阵](../artifacts/rf7/matrix-validation.json)、[离线报告](../artifacts/rf7/offline-validation.json)。

## 视觉判读与差异边界

末尾集中人工核对的窗口截图：

- [1100×820 中宽窗口](D:/Project/GaussianReadPro/artifacts/rf7/source-matrix-en-mid-1100-1a8d1171/default-3d.png)：工具条横向滚动可达，按钮文字不越界，方向立方体与底栏分离，tooltip 避开纵轴。
- [840×680 / DPR2 冻结 EXE 详情抽屉](D:/Project/GaussianReadPro/artifacts/rf7/frozen-matrix-cn-narrow-dpr2-b164cac2/default-3d.png)：实际 1680×1360 像素原图，抽屉覆盖部分主图并可滚动，收起按钮保留。
- [新进程恢复后的表达式页脚](D:/Project/GaussianReadPro/artifacts/rf7/frozen-restore-default-3355deec/editor-fresh-process.png)。

参考原图：[energy-profile-replica-target.png](design/energy-profile-replica-target.png)。[50% 叠加](../artifacts/rf7/visual-comparison/derived-overlay-50pct.png)、[差异热图](../artifacts/rf7/visual-comparison/derived-difference-heatmap.png) 是诊断衍生图，不能当作真实程序截图；[分区测量](../artifacts/rf7/visual-comparison/comparison.json) 没有掩码。

| 区域 | 判读 |
| --- | --- |
| 顶部与导航 | 内容区高度/侧栏边界、选中导航位置对齐；显示用户要求的新名称。原生 Windows 标题栏按钮位于内容截图之外，保留操作系统窗口行为。图标来自当前随包 SVG 资源。 |
| 主图 | 两路径、渐隐面积幕、圆节点/细亮环/tooltip、方向立方体和底部工具条齐全。节点/表格使用一致的真实能量；修正参考图 TS1 名称笔误及标注数值与几何高度不一致，默认图体位置因此存在差异，不作像素级等同承诺。 |
| 右栏 | 分子、七类键值、概览、表格均绑定真实数据。合成来源只有 4 个原子，不冒充参考图苯环；多来源公式明确显示 Multiple sources/Multiple。 |
| 路径控件 | 用户追加的完整路径列表与“+”占用原路径组内位置；不是参考图原有控件。 |
| 字体与配色 | 标准节点 16/17 DIP、轴 14 DIP；标准样例主图标签无重叠。深色对比度和无文字背景采样分别测量；浅色仅作可用性回归，不套用深色图像差阈值。 |

全区域平均像素差只用于定位上述变化，不能用大片深色背景抵消曲线/文字差异。宏观边界检查与实际截图人工检查分开记录；不宣称逐像素复制。

## 复现命令

在项目目录、锁定的 `.venv` 下运行：

```powershell
.venv\Scripts\python.exe tools\run_rf7_tests.py
.venv\Scripts\python.exe tools\build_windows.py
.venv\Scripts\python.exe tools\check_windows_bundle.py
.venv\Scripts\python.exe tools\check_profile_rf7.py --runtime source
.venv\Scripts\python.exe tools\check_profile_rf7.py --runtime frozen
.venv\Scripts\python.exe tools\run_rf7_matrix.py
.venv\Scripts\python.exe tools\check_rf7_offline.py
.venv\Scripts\python.exe tools\audit_rf7_bundle.py
.venv\Scripts\python.exe tools\summarize_rf7.py
```

离线检查自动建立唯一的新目标文件夹。`tools/run_rf7_final.py` 串行运行最终回归、烟测、源码/EXE 主链、矩阵、离线与包审计，避免多个原生窗口互相抢焦点。仅修改外部 JS/CSS 时可用 `tools/refresh_rf7_resources.py` 同步资源、重写 manifest 并重新压缩；最终仍核对 ZIP/EXE/资源 SHA 并运行实际 EXE。完整输出在 `artifacts/rf7/`，早期失败记录保留。

## 发现与修复、限制

- 初次全量回归发现中英文语言键不一致，已补齐；初版冻结 SVG 缺少动态加载后端，真实 EXE 验收暴露后补齐 SVG/PDF。此前仅 PNG 烟测不足，现对三格式逐一运行。
- QA 本身也曾有错误：合成夹具 oracle 小数来源混淆、过长 QTest.qWait 导致 Python worker 被 GIL 阻塞、鼠标默认延迟影响 FPS、连续切换后未等渲染稳定、一个新增测试写错导入。早期运行目录和主要失败日志保留，修复项以最终复跑为准。
- 中间 EXE 运行 `artifacts/rf7/frozen-primary-default-90c1cf75` 的 27 项中，功能与保存/导出已通过，详情延迟 p95 为 205.1 ms，超过 200 ms 目标，明确保留为未通过运行。该验证器仍用短 QTest.qWait 等待后台任务；最终将等待改为释放 GIL 的 QEventLoop，与生产 QApplication.exec 一致，再使用同一观察方式复跑源码与 EXE。不能把中间结果改记为通过。
- 本机系统临时目录 ACL 导致一次 pytest setup 失败，最终使用工作区唯一 basetemp；pytest cache 写入权限警告不影响断言。构建日志有未使用 Qt QML 插件缺失警告，实际 Widgets/WebEngine 入口与导出实测通过才计入验收。
- 内存分别记录 UI/WebEngine private bytes 和工作集；没有 GPU 显存测量，不宣称所有资源零增长。默认调度、其他硬件、macOS/Linux 未验；未启动 RF8/S8/S9，其他分析页仍按既有阶段状态。
