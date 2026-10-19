# S0 合成日志基准

参考图专项 RF0 的双路径视觉夹具见 [profile_replica](profile_replica/README.md)。

这些 `.log` 文件均为人工缩减片段，不是 Gaussian 原软件完整输出，也不能证明生产兼容性。`expected.json` 中的能量、作业范围、终止类型和行号为人工给定 oracle；后续实现必须按来源核查，不能从旧解析器自动生成预期。

样本包含：正常多次 SCF、单点、多个作业、末作业失败、截断、E/D 指数、无法识别字段，以及不同目录下同名文件。边界用 `Entering Gaussian System` / 正常或错误终止明确表达；S1 必须补充真实 Link1/复合作业格式的核对样本。

运行 `tools/check_baseline.py` 可检查 oracle 与对应日志行、计算基准，并生成旧解析器差异报告。这里只验证 fixtures 和原程序基线，不是 S1 解析器测试。
