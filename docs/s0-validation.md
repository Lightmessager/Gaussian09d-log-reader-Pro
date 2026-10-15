# S0 验证记录

本阶段验证 Python/Qt/离线 Plotly 的技术链路与基准输入，不包含生产解析器、最终界面或真实日志认证。

## 环境与版本

- Windows 11，64 位，当前主机。
- Python 3.12.14 项目 `.venv`；系统默认 Python 3.15 未修改。
- PySide6 6.12.0 / Qt WebEngine 6.12.0.140。
- Plotly Python 7.1.0，内含 Plotly.js 4.1.1。
- PyInstaller 6.22.3，pytest 9.1.1。
- 精确 Windows 安装依赖：`requirements-s0-lock.txt`。

原始脚本 SHA256：`befc3306317b13e56c64c5cf379e9d25273ff389240f1a1d840e133036bd0b7b`。

本地 Plotly.js SHA256：`d1b35fcc41b2eb43a7804f6317e5c73761c26d1724810ae695690dd92a73fa1e`；4,819,433 字节。由安装包提取，保留其许可头；原型运行不导入 Plotly Python 包。

## 基准证据

`tools/check_baseline.py` 校验 9 份人工合成样本、明确行号、默认正常作业选择和十进制计算基准。`pytest -q`：4 passed。样本核对包括错误行号和错误参考值应被检测。

旧程序基线差异：

| 情形 | 证据 |
|---|---|
| E/D 指数 | 旧规则把 SCF/free 的指数截掉，带加号的热校正未匹配 |
| 末作业失败 | 取到失败作业 -76 Hartree；本契约默认应选前一正常作业 -75 并显示警告 |
| 截断日志 | 能量 -20 被取出但没有未结束状态；默认正常作业选择应 unavailable，显式选取才可带警告使用 |
| 跨作业来源 | multi_job 与 last_job_failed 中 SCF 与热化学字段属于不同作业，旧返回元组无法区分 |
| 未知变量 | `R_missing` 被前缀匹配到 R 并返回 -150；新契约必须拒绝 |
| 布尔常量 | `True` 被当作数值接受；新契约必须拒绝 |

详细结果：`artifacts/s0/baseline.json`。报告中的默认作业预期与来源直接来自人工 oracle，不由旧解析器生成。

## 源码图表验证

最终 `source-smoke.json` passed=true：本地页面、WebChannel 握手、Plotly SVG、4 个 Python 值保持、QTest 点击 TS1 后经 JS/桥接回传对应 UUID，均成功。无 JavaScript 错误、无远程资源请求；允许资源只有 file/qrc。`source-preview.png` 人工检查中文、坐标轴、参考线、悬浮值和选择状态。

定位过程：Codex 受限进程环境中曾出现 WebEngine renderer AbnormalTermination/exit 49；在正常桌面权限下最终验证通过。不能仅凭退出码断言底层故障原因；原型未使用 `--no-sandbox` / `--single-process`。另一处问题为 JavaScript 坐标对象回传，改为 JSON 序列化后点选链路通过。

## 打包与平台矩阵

Windows frozen onedir 最终自测 `passed=true`，退出码 0；同样验证了实际鼠标点选、离线资源和数值传输。源码与 frozen 的 Plotly SHA256 和渲染数值一致。`frozen-preview.png` 已人工检查，中文和悬浮读数正常。

演示包：`dist/GaussianReadPro-S0/GaussianReadPro-S0.exe`，必须保留整个目录。共 3107 文件，597,913,429 字节（约 598 MB / 570 MiB）。WebEngineProcess、本地 HTML 和 Plotly.js 已检查存在；`artifacts/s0/summary.json` 保存汇总证据。该体积包含自动收集的 Qt/QML 资源，S9 应评估精简，不能把精简后的包沿用当前验证结果。

首次 frozen 启动因错误 ICU DLL 无法导入 QtCore；PE 导入/导出校验定位到宿主 Poppler 的版本化 ICU API。spec 排除外部 `icuuc.dll`/`icudt78.dll` 后由本机系统 ICU 解析，最终运行通过。详细决定见 D008。构建时曾出现本机 DLL 锁和一次分析器异常，最终重新构建成功；启动诊断由 `tools/check_frozen.py` 捕获，避免无日志等待。

| 范围 | 状态 |
|---|---|
| Windows 当前主机源码运行 | 已通过 |
| Windows 当前主机 frozen 运行 | 已通过 |
| Windows 干净机器/安装器 | S9 待测 |
| macOS 本地构建/运行 | 无该平台环境，待平台执行 |
| Linux 本地构建/运行 | 无该平台环境，待平台执行 |
| 真实 Gaussian 多作业/Link1 | 尚无真实样本，S1 待校准 |

风险记录：WebEngine 包体和资源依赖较大；三平台字体、WebGL 和分发行为需要各自验收；PyInstaller 曾提示未使用 QML assetdownloader 插件缺失，当前 Widgets/二维图表 frozen 流程不受影响，不能据此证明未使用 QML 功能完整。S0 固定资源路径、协议握手和可重复自测，为后续阶段保留证据。
