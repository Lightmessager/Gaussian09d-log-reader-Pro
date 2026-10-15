# G5 动效与本机偏好验证

2026-10-15。用户明确要求暂不继续底层崩溃排查、继续开发，因此以已验证的本机临时启动方案推进 G5。G4 默认调度原生崩溃仍未关闭，不宣称硬件故障已修复，也未修改系统、BIOS、正式依赖或默认跨平台入口。

## 实现

- `storage/preferences.py` 增加 `visual_effects=standard|reduced` 与严格 bool `reduce_motion`。只接受完整旧 v1 键集并补默认，读取不写回；保存仍严格验证完整新键集。未知键、部分缺字段及错误类型不能覆盖原偏好。
- `ui/main_window.py` 顶栏齿轮菜单加入“减少视觉效果 / Reduce visual effects”“减少动态效果 / Reduce motion”，宽窄布局均可访问，经现有 `controller.update_preferences` 合并排队。切换只改本机偏好，科学数据/SQLite v1 不变。
- `ui/glass_widgets.py` 新增有限按钮使用的 `GlassButton`：悬停/焦点边缘 140ms，鼠标按下/释放 90ms。每个按钮只有一个复用动画，隐藏立即停止；减少动效时立即更新。没有 widget-tree 模糊/透明度、表格动画或新永久计时器。
- `ui/theme.py` 统一同步现有玻璃面板和按钮；新建面板从应用属性继承材质，因此表达式/批量弹窗无需修改科学逻辑即可继承实色模式。减少视觉效果与减少动态效果独立。CN/EN 资源已补齐。

## 实际检查

全部使用原 `.venv` Python 3.12.14，并通过 Windows `start /affinity FFFFFF3F` 排除逻辑 CPU 6、7，只影响启动的进程。保持 Chromium sandbox，使用独立 QA 项目和 INI 文件，不读取或覆盖用户工作。

回归执行条件：`QT_QPA_PLATFORM=offscreen`、`PYTHONPATH=D:\Project\GaussianReadPro\src`，`pytest -q --tb=short -p no:cacheprovider --basetemp=<工作区内全新目录>`。

| 测试文件 | 结果 |
| --- | --- |
| test_glass_preferences.py、test_storage_sources.py、test_workbench.py、test_node_editor.py | 65 passed in 51.74s |
| test_plot_spec_export.py | 20 passed in 11.65s |

新增测试覆盖旧偏好只读迁移、严格类型与键集、无效保存不覆盖、忙碌期间最后选择保存、科研状态不变、新面板继承、双语文案、动画复用/停止及立即减少动效。没有重跑历史 S7 全量。

真实 Qt：以同一亲和性启动 `.venv\Scripts\python.exe -u tools\check_glass_g5.py`。最终报告 `artifacts/ui-glass/g5/523e1e4ad64f47ae9272134229e13189/validation.json`，`passed=true`、`platform=windows`、`process_affinity=0xffffff3f`、无 controller 错误，4 组 G5 专项检查通过：

1. 宽窄窗口、中英与浅深主题、减少材质、外观入口可见且在顶栏边界内。
2. 忙碌期间偏好排队保存，项目对象和 revision 不变。
3. 减少动效立即更新，等待后所有按钮动画停止。
4. 关闭后新建 controller/window 重新读取同一 INI，恢复两项设置；保存重开的项目中，批量弹窗继承实色材质。

窗口尺寸与语言切换验收比较所有科研结果字段，仅归一化结果的 `revision`：窗口/分隔条工作区保存本身会推进修订，不能据此认为能量发生变化。另有无窗口调整的偏好测试，严格比较完整项目及计算结果。

以下 6 张真实 Qt 截图均已实际查看，位于上述最终运行目录：

- `standard-cn-light.png`：1440×920 中文浅色标准材质。
- `standard-en-dark.png`：1440×920 英文深色标准材质。
- `reduced-en-dark.png`：1100×820 英文深色减少效果。
- `reduced-cn-compact.png`：860×680 中文紧凑减少效果，顶栏外观菜单可达。
- `appearance-menu-cn.png`：两项菜单均选中。
- `reopened-reduced-dialog-cn.png`：重启后批量弹窗实色材质、中文字体正常。

保留失败记录：初次回归因 G5 输出父目录不存在产生 setup 错误，创建父目录后完成 65 项；原生运行 `0402f103b61b4985add8b2af67bca8c9` 因未排除结果 revision 差异而失败；`c84b131bb40847cca74394492588f551` 因验收脚本在无路径空项目上打开批量编辑器而失败。最终脚本改为保存并重新打开四节点项目，没有修改产品编辑器来绕过错误。

## 限制与下一步

G5 专项通过不等于整套 UI/平台验收。截图中 860×680 的反应路径页图表可用高度不足，工具行/轴标签/提示挤压；1100×820 也存在轴标题与提示接近的情况。英文完整侧栏标题有省略。G6 应优先处理这些布局问题并补矩阵，不能把外观菜单可达断言说成完整图表布局通过。

当前仅 Windows 现有桌面缩放，未完成 100%/150%/200% DPI、macOS/Linux、性能/内存/打包验证。G4 默认调度崩溃仍保留条件，不进入 S8。下一阶段 G6。
