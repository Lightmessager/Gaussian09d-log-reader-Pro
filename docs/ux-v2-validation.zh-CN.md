# GaussianReaderPro UX v2 总体验收

日期：2026-10-18

## 状态

U0–U7 源码阶段与本机路线验收已完成；用户随后启动 U8，Windows x64 2.0.0 便携包已全量构建。冻结包审计 10/10、默认首页的 EXE 新建/保存/改名/搭建点击路线通过，Agg PNG/SVG/PDF 通过。WebEngine 页面烟测在源码和冻结 EXE 均失败，详见 U8 报告；本机浏览器页面/3D 仍未验收通过。

U7 桌面路线中 WebEngine 本地图表页面加载失败，应用切换到原生二维曲线并成功导出 HTML 数据包。U8 延续复现同一 WebEngine 页面失败；包内静态 Agg 导出已通过。真实 Gaussian16 三日志只用于来源、SCF 行、保存和重开验证；其相对能量均为 0 Hartree，不能据此宣称测得非零势垒。

## 阶段记录

| 阶段 | 范围与验收 | 记录 |
|---|---|---|
| U0 | 现状、冻结包和用户数据边界基线；本轮做只读复核 | [基线](ux-v2-baseline.zh-CN.md) |
| U1 | 默认能量页编辑入口、统一动作和路径路由 | [入口验证](ux-v2-u1-validation.zh-CN.md) |
| U2 | 项目名/保存状态、最近项目和首次保存命名 | [项目状态验证](ux-v2-u2-validation.zh-CN.md) |
| U3 | 导入摘要、UUID 作业候选、来源失效重连与旧路径转换 | [导入与兼容验证](ux-v2-u3-validation.zh-CN.md) |
| U4 | BuilderDraft、路径画布、连线/分支与局部详情 | [画布验证](ux-v2-u4-validation.zh-CN.md) |
| U5 | worker 预检、可定位诊断、应用/保存状态机和重试 | [预检与保存验证](ux-v2-u5-validation.zh-CN.md) |
| U6 | 草稿恢复、退出守卫、键盘操作和 DPR 窗口矩阵 | [草稿与窗口验证](ux-v2-u6-validation.zh-CN.md) |
| U7 | 默认首页路线、双路径、真实日志往返、兼容测试与交接 | [U7 验证](ux-v2-u7-validation.zh-CN.md) |
| U8 | Windows 2.0.0 全量构建、包审计、静态图和 EXE 首页点击验收 | [U8 验证](ux-v2-u8-validation.zh-CN.md) |

U7 自动化桌面结果和机器可读细节位于 [`u7-validation.json`](../artifacts/ux-v2/u7/u7-validation.json)。U8 包审计见 [`bundle-audit.json`](../artifacts/ux-v2/u8/bundle-audit.json)，EXE 桌面路线报告与截图位于 `artifacts/ux-v2/u8/29199ad342fe413ba0b4e687c48a4be8/`；发行包路径和 SHA 见 U8 报告。

## 总体边界

- 使用 UUID/source/job 身份，科学 AST、能量类型、零点和 SQLite v1 语义保持既定约束。
- 合成路径 fixture 与真实日志分别记录；空值不补零，真实日志等能量不被称为势垒。
- 当前结果验证 Windows 源码路线和 2.0.0 冻结包。macOS/Linux 与其他 Windows 环境仍须分别运行和验收。
- 当前工作区无 `.git`，阶段文档保留已执行命令、退出码、证据路径和限制。
