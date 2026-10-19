# L2 深色主题提亮与净化：实施与验收记录

日期：2026-10-17。状态：**主题与结构页修改完成；图表真实截图验收受本机 WebEngine 页面加载失败阻塞，阶段暂不判定通过。**

## 修改

- `src/gaussianreadpro/resources/themes/lavender_sunset.json`：重整深色画布、面板、输入、工具栏和选中层次；增强深浅主题通用描边与禁用文字；压低能量图背景辉光色，增强深色面板边界，并加深浅色图表橙色路径/焦点。
- `src/gaussianreadpro/ui/glass_widgets.py`：全局背景两层辉光 alpha 从 96/66 降为 34/24；普通卡片边界改用边框 token，弱化亮白描边。
- `src/gaussianreadpro/ui/theme.py`：将 QPalette 的 Mid 映射到 muted token，供自绘控件使用一致的次级文字色。
- `src/gaussianreadpro/ui/analysis_pages.py`：结构视图连线、原子轮廓和说明文字改随主题绘制；元素符号按原子球填充色选择明/暗文字，避免白字落在浅色氢球上。
- 回归预期同步更新 `tests/test_workbench.py` 与 `tests/test_plot_spec_export.py` 的颜色断言。

未改科学数据、路径计算、项目修订或保存内容。浅色主题保留原背景和文字色，只增强通用边界、禁用文字和图表橙色信息。

## 对比度核算

使用 sRGB 相对亮度/对比度公式，以实际不透明 token 背景计算；profile 半透明面板和边框先与画布合成。数值为对比度比值，文字目标至少 4.5:1，关键边界与图形目标至少 3:1。

| 主题 / 项目 | 对比对象 | 比值 | 结果 |
| --- | --- | ---: | --- |
| 浅色 | 正文 / 画布 | 13.79:1 | 通过 |
| 浅色 | 次级文字 / 面板 | 5.47:1 | 通过 |
| 浅色 | 禁用文字 / 面板 | 4.92:1 | 通过 |
| 浅色 | 控件边框 / 输入框 | 3.36:1 | 通过 |
| 深色 | 正文 / 画布 | 17.04:1 | 通过 |
| 深色 | 次级文字 / 面板 | 10.15:1 | 通过 |
| 深色 | 禁用文字 / 面板 | 7.15:1 | 通过 |
| 深色 | 控件边框 / 输入框 | 3.45:1 | 通过 |
| 浅色能量图 | 轴文字 / 画布 | 7.82:1 | 通过 |
| 浅色能量图 | Path A / Path B / 焦点线 / 画布 | 5.36 / 3.62 / 3.62:1 | 通过 |
| 浅色能量图 | 合成面板边框 / 面板 | 3.51:1 | 通过 |
| 深色能量图 | 轴文字 / 画布 | 10.56:1 | 通过 |
| 深色能量图 | Path A / Path B / 焦点线 / 画布 | 6.89 / 10.28 / 9.33:1 | 通过 |
| 深色能量图 | 合成面板边框 / 面板 | 3.19:1 | 通过 |

## 截图与验证

可见主窗口在 1440×900 DIP 窗口尺寸下实机抓取，系统 DPR 1.25，因此 PNG 为 1800×1125 像素。首页显示空项目状态；结构页使用明确的合成 C/O/H/H 四原子坐标，只核查球棍标签、表格与主题，不作为 Gaussian 科学数据。

| 页面 | 浅色 | 深色 |
| --- | --- | --- |
| 首页 | `artifacts/l2/home-final-light.png` | `artifacts/l2/home-final-dark.png` |
| 结构页 | `artifacts/l2/structure-final-light.png` | `artifacts/l2/structure-final-dark.png` |

最终代码与色值修改后的聚焦回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_glass_preferences.py tests/test_workbench.py::test_language_and_theme_switches_preserve_science_and_workspace tests/test_plot_spec_export.py::test_chart_visual_style_tracks_glass_theme_and_keeps_paper_export_neutral tests/test_plot_spec_export.py::test_independent_chart_theme_survives_native_fallback -q
```

结果：**15 passed**。同一轮较大主题/工作台/图表/结构回归结果 **77 passed**（最终边框 alpha 与浅色禁用色随后另由以上 15 项覆盖）。

尝试用 `tools/check_profile_rf7.py --runtime source --phase primary --case l2-dark --size 1672x941 --dpr 1 --language en --theme dark` 抓取能量图实际窗口，退出码 1，报告 `RF7 timeout`，原因为“本地图表页面加载失败”；无 JavaScript 错误，但没有产生有效图表截图/视觉检查结果。此 WebEngine 本机限制在既有 RF8/RF7 记录中已有记录。本轮的图表 token 对比度及主题切换由回归覆盖，不能替代实际图表的双主题、两条路径与悬停/选中态桌面检查。

**结论**：首页和结构页深浅主题的真实窗口截图及对比度目标通过；图表实际渲染验收仍缺证据，因此按项目书停在 L2，不进入 L3。需要在 WebEngine 页面可正常加载的桌面环境补做能量图深浅主题截图和两路径状态检查后，才能将 L2 标为全部通过。
