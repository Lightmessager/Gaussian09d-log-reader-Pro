# UX v2 U6 验收：草稿保护、键盘与适配

日期：2026-10-18

## 完成范围

- 新增 `gaussianreadpro.builder-draft` v1 草稿文件格式，使用项目/路径 UUID 固定位置，2 MiB 上限，同目录临时文件原子替换。损坏、越界、身份不符和写入中断不会覆盖有效旧稿。
- 草稿读写、删除通过 SessionBackend 的单线程 worker；恢复需要用户明确点击检查，按项目与路径 UUID 加载，作为未应用草稿恢复。修订不一致会标记冲突；预检成功之前不能应用。应用并保存成功后只删除相同代次的恢复副本。
- 关闭、取消、Esc、窗口关闭和路径切换共用退出守卫；保存失败时窗口保留。只读项目可复制草稿文本，不写项目或恢复目录。
- 支持阶段列表方向键、Enter、Delete（可撤销）、Tab 导航、搭建器范围内 Ctrl+S，文本编辑框 Ctrl+Z 仍由原生编辑器处理。问题清单定位阶段时会滚动详情区并聚焦标签字段。
- 添加搭建器中英切换入口方法；主题、减少视觉效果/动效、尺寸变化不重建 BuilderDraft、不改变 generation 和选中阶段。

## 自动化验证

| 命令 | 结果 |
|---|---:|
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_builder_drafts.py -q` | 37 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_builder_save_flow.py -q` | 13 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_reaction_network.py -q` | 13 passed |
| `.venv\Scripts\python.exe tools\run_pytest_compat_windows.py tests\test_storage.py tests\test_storage_sources.py -q` | 55 passed |
| `python -m json.tool` 校验 `zh_CN.json` 和 `en_US.json` | 均通过 |

旧反应网络界面测试原来在 `dialog.close()` 后等待 U6 新增的退出选择框。测试夹具改为明确选择丢弃测试草稿后，整组 13 项通过。U5 保存流程本轮完整重跑通过；此前单进程 Qt 中止在这次复测中未复现。

## Windows 原生 Qt 桌面矩阵

每个 DPR 使用独立进程：

```powershell
.venv\Scripts\python.exe tools\verify_u6_draft_protection.py --dpr 1
.venv\Scripts\python.exe tools\verify_u6_draft_protection.py --dpr 1.5
.venv\Scripts\python.exe tools\verify_u6_draft_protection.py --dpr 2
```

三次命令均退出码 0，每档生成 12 张截图，覆盖中/英文、light/dark、减少/标准视觉效果，以及 840×680、1100×820、1440×900 请求尺寸。每次变更后脚本检查同一草稿对象、generation 与选中阶段，检查主要按钮可见/可达、有无障碍名称、按钮文案单行宽度，以及 `物质列表 → 阶段列表 → 阶段标签` Tab 焦点链。

| 请求 DPR | 实测 DPR | 屏幕可用逻辑区域 | 实际窗口尺寸 | 屏幕约束 |
|---:|---:|---:|---|---|
| 1.0 | 1.0 | 2560×1440 | 840×680、1100×820、1440×900 | 无 |
| 1.5 | 1.5 | 1707×960 | 840×680、1100×820、1440×900 | 无 |
| 2.0 | 2.0 | 1280×720 | 840×680、1100×708、1264×708 | 8 个大尺寸组合受屏幕边界约束 |

当前显示器的 125% 系统缩放下，工具分别采用 Qt scale factor 0.8、1.2、1.6，报告中同时保存系统 DPI、Qt scale factor 和实测 DPR。DPR 2 的 1100×820 与 1440×900 无法在当前 1280×720 逻辑工作区完整显示；矩阵按工作区安全尺寸截图，没有把受约束尺寸记作目标尺寸通过。

报告与截图：

- DPR 1：[`validation.json`](../artifacts/ux-v2/u6/dpr-1/validation.json)；[840×680 中文 / light](../artifacts/ux-v2/u6/dpr-1/840x680-actual840x680-zh_CN-light-r1.png)
- DPR 1.5：[`validation.json`](../artifacts/ux-v2/u6/dpr-1.5/validation.json)；[1100×820 英文 / dark](../artifacts/ux-v2/u6/dpr-1.5/1100x820-actual1100x820-en-dark-r1.png)
- DPR 2：[`validation.json`](../artifacts/ux-v2/u6/dpr-2/validation.json)；[受屏幕约束的 1264×708 英文 / dark](../artifacts/ux-v2/u6/dpr-2/1440x900-actual1264x708-en-dark-r1.png)
- 矩阵脚本：[`verify_u6_draft_protection.py`](../tools/verify_u6_draft_protection.py)

## 已知限制

- 840×680 下物质库和右侧详情需要使用水平/垂直滚动；这是现有三栏布局的窄窗行为。底部应用、预览、取消等主要动作仍在可视区。矩阵验证了可滚动与操作可达，没有把窄窗描述为无滚动布局。
- 本矩阵使用明确标注的合成阶段，不包含真实 Gaussian 日志或冻结包验证；真实用户完整路线属于 U7。
- 英文切换覆盖 U6 的退出、恢复、快捷键、辅助名称和已登记静态文本；搭建器历史科学字段中仍有部分文案显示中文，未在 U6 扩展成全量界面翻译验收。
- 工作区没有 `.git`，无法提供分支、提交或 Git diff。

## 阶段状态

U6 源码、自动化用例、原生桌面矩阵与证据记录已完成。U6 阶段记录时 U0 完整基线仍未完成，现已完成并见 `docs/ux-v2-baseline.zh-CN.md`；U7 真实用户路线、冻结包和完整交接尚未开始。
