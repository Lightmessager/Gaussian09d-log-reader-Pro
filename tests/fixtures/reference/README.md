# S1 真实输出来源

3 个完整输出取自 cclib 官方仓库 `data/Gaussian/basicGaussian16`，固定提交 `76df867532961117427cb3e0877913db3233f83f`。仓库 BSD 3-Clause 许可全文保留在 `LICENSE.cclib`。输出本身保持原始字节，不添加 synthetic 标记、不改行号。

`expected.json` 中能量、行号、终止和元数据是逐项检查原始文本后给定的预期；SHA256 用于检测样本漂移。样本覆盖单点、优化的多个 SCF 周期、频率热化学和真实内部 `Entering Link 1` 启动。测试还将 ir/sp 在临时目录拼接，验证多次 Gaussian 启动后的来源隔离；拼接输入属于测试派生数据，不声称为原软件原生 Link1 输出。

原生多步 Link1、Gaussian03/09、用户自身的不同计算方法与失败输出仍需扩充实测样本；现有合成测试覆盖约定的 Link1 运行时标记和错误分支。

固定来源：[单点](https://github.com/cclib/cclib/blob/76df867532961117427cb3e0877913db3233f83f/data/Gaussian/basicGaussian16/dvb_sp.out)、[优化](https://github.com/cclib/cclib/blob/76df867532961117427cb3e0877913db3233f83f/data/Gaussian/basicGaussian16/dvb_gopt.out)、[频率](https://github.com/cclib/cclib/blob/76df867532961117427cb3e0877913db3233f83f/data/Gaussian/basicGaussian16/dvb_ir.out)。


The three `.out` files are intentionally not distributed with this repository because their Gaussian headers contain confidentiality and license notices. The reference-log regression module skips when these local-only files are absent. Obtain and use copies only under the applicable Gaussian license.
