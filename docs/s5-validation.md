# S5 验收记录

S5 为现有 Qt 工作台接入运行时中文/English、浅色/深色和跟随系统主题。新安装的语言偏好为 `system`，启动时按系统 locale 选择中文或英文；手动切换后保存明确语言。控件、来源/节点表头、状态、属性证据和二维预览由同一翻译入口处理；`zh_CN.json`、`en_US.json` 随包离线提供，缺少翻译时回退源文本。用户项目名、文件名、用户标签、表达式和 UUID 不翻译。

语言和主题保存在现有 `LocalPreferences`，通过 ProjectController 的串行后台操作落盘。它们不进入 Project、SQLite schema 或科研 revision。切换语言会重新投影视图，保留稳定 ID 选择、搜索、路径排序、列排序、筛选与计算结果；状态筛选按固定状态码匹配，不依赖翻译后的文案。浅/深 QSS tokens 在 `ui/theme.py`，system 模式参考 Qt palette。

验证命令：

```powershell
.\.venv\Scripts\python.exe -m compileall -q src\gaussianreadpro
.\.venv\Scripts\python.exe -m pytest -q
```

新增用例切换中文→英文→中文和深色主题，断言项目 revision、计算数值、筛选文本、选中 node UUID 保持，且偏好已写入本机设置；另检查中英文 JSON 键集合相同。完整 S4+S5 回归共 219 项通过。当前未做 macOS/Linux 视觉验收；少数底层 Gaussian 诊断仍按稳定 code 原文展示，后续可依 code/params 表补齐用户友好翻译。S5 未改变 S4 的原生二维预览边界，完整交互图仍在 S7。
