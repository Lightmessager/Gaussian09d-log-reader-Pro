# RF4 合成结构/能量夹具

由 `tools/build_profile_rf4_fixture.py` 生成，独立于 RF0 日志。8 个源文件各包含一个独立作业、一个 Input orientation 和一个 Standard orientation；后者是四原子 C/O/H/H 的人为坐标。数值、TS 标签与坐标不是一次真实 Gaussian 计算的结果，不能用于科学验证。

用于验证：精确作业边界、Standard 优先、Angstrom 单位、原子与行号/SHA 可追溯、主图/详情/概览/表格 ID 联动。界面明确显示“合成示例”。参考/势垒和跨路径步骤 ID 配对均在生成器中显式设置，不靠标签或数组长度猜测。

能量 oracle 与 RF0 一致：A 为 0 / +15.060 / −5.020 / −15.688，B 为 0 / +11.420 / −2.800 / −12.400 kcal/mol。核对使用项目统一的 Hartree 换算常数；显示采样和连接键均不参与能量运算。
