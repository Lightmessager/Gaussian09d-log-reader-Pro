# S1 验证与交付记录

完成日期：2026-10-15。范围：独立的数据模型、Gaussian SCF/Gibbs 分作业解析、单位换算与命令行核查。当前验证主机为 Windows 11 / Python 3.12.14。

## 交付

- `core/models.py`：文件、作业、能量、元数据、稳定引用、解析/选择结果与诊断；frozen dataclass 和只读映射。
- `core/parser.py`：有界流式读取、完整文件 SHA256、明确作业边界、最后有效字段及原始数字/行号、终止/收敛分开、精确作业选择、取消和读取失败、读中变更检测。
- `core/units.py`：内部 Hartree，Hartree/kcal·mol⁻¹/kJ·mol⁻¹ 转换；版本化 NIST CODATA 2022 常数和热化学卡路里定义。
- `tools/inspect_log.py`：无 GUI 的 JSON 快照核查；`tools/check_s1.py`：基准和流式性能证据。
- 3 份 cclib 固定提交的真实 G16 日志及其 BSD 3-Clause 许可、人工预期与 SHA256。

## 正确性

`python -m pytest -q`：**71 passed**。包括原有 S0 oracle 验证以及 S1 行为测试：

- 9 份合成日志的作业范围、数值、来源行号与默认选择。
- 真实单点、优化、频率日志，包含最后 SCF、Gibbs 校正/总值、方法/基组/电荷/温度来源。
- 两份真实输出拼接后来源和元数据隔离；绑定后缺 Gibbs 不借用其他作业。
- Link1 运行时边界与普通内部 link 的区分；缺失正常结束时不自动选择。
- 正负数、小数、E/D 指数；错误和非有限值被拒绝，不截断指数或补 0。
- 文件缺失、空文件、权限失败、读取中 I/O 失败、取消和读中变更的独立状态。
- 改名/相同名称不改变身份规则；重复解析和追加新作业保留未改变作业的 ID，内容变化改变 ID。
- 异常长行、异常路线、巨大整数元数据、诊断限额；快照不可修改，JSON 不包含 NaN/Infinity。
- 单位往返、溢出、非法类型与固定/跟随引用约束。
- 新进程在 `python -S` 下成功导入 core，不加载 PySide6、Plotly、Tkinter 或 NumPy。

基准报告 `artifacts/s1/validation.json` 对 12 个固定样本逐项核对通过。原始参考脚本 SHA256 仍为 `befc3306317b13e56c64c5cf379e9d25273ff389240f1a1d840e133036bd0b7b`。

人工核对的真实频率结果来自 `dvb_ir.out`：SCF=-382.308266602（457 行）；Gibbs 热校正=0.143352（2057 行）；总自由能=-382.164915（2061 行）；298.15 K / 1 atm（2006 行）。数据按各自输出精度保留，不通过其他舍入字段重新推导替代原值。[固定上游输出](https://github.com/cclib/cclib/blob/76df867532961117427cb3e0877913db3233f83f/data/Gaussian/basicGaussian16/dvb_ir.out)

## 流式测量

在同一主机，对单作业稀疏合成大文件使用 tracemalloc：

| 输入字节 | Python 分配峰值 | 解析时间（开启追踪） |
|---|---|---|
| 2,097,240 | 17,568 | 0.217 s |
| 16,777,304 | 17,537 | 2.598 s |

文件增大时峰值没有按文件大小增长；原始文本没有一次读入。数值为本机样本实测，tracemalloc 不等于进程 RSS；结果还会随作业数量、诊断和元数据数量增长。异常超长单行有独立测试，取消会在分块读取处检查。

## 使用

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\check_s1.py
.\.venv\Scripts\python.exe tools\inspect_log.py tests\fixtures\reference\dvb_ir.out --output artifacts\s1\frequency-snapshot.json
```

`--kind scf|gibbs_correction|gibbs_total` 控制核查字段；可用返回 0，不可用返回 1。重放固定作业时同时传上次快照的 `--source-id` 和 `--job-id`；已在频率样本上验证重放成功。

## 范围与下一阶段

真实样本目前覆盖 G16 的单点、优化、频率。原生多步 Link1、Gaussian03/09、复合方法和用户实际失败日志仍需扩充；已用合成输入验证已约定的边界和错误分支。S1 不将 SCF 值当作 CC/MP/ONIOM 总能量，不进行过渡态、化学计量或全部计算条件的自动证明。

S1 没有改动 GUI 流程，因此本阶段没有重复 Qt 或 frozen 自测；S0 演示包仍展示固定合成数据。下一步 S2 实现有类型的表达式、节点体系能量与统一参考，复用当前 EnergyRef 和 JobSelection；收到缺值/来源警告时不能忽略或补 0。存储与正式 UI 按 S3/S4 执行。
