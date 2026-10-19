# GaussianReaderPro Academy

GaussianReaderPro 2.0.0 中文交互教程。毛玻璃面板、流动极光、分子球棍模型、可点击能量图、14 个课程和 42 个操作目标。

## 打开

最方便：双击 `artifacts/GaussianReaderPro-Academy.html`。这是内嵌所有脚本和样式的单文件版本。

直接用现代浏览器打开 `dist/index.html`。保留整个 dist 文件夹，页面资源均在本地，无需安装前端依赖。

也可以在本目录运行 `python -m http.server 8765 --bind 127.0.0.1 --directory dist`，访问终端显示的本地地址。

## 使用

- 首页点击“开始交互学习”，或在左侧任选课程。
- 根据右侧步骤在操作台完成目标，按钮亮起后继续。
- “探索全部模块”浏览课程，右上角搜索支持按钮名和关键词。
- 点击右上角音效按钮主动开启声音；齿轮设置音量和动态程度。
- 学习进度保存在当前浏览器，可在设置中清空。
- CSV / SVG 下载为合成教学示例。网页不运行 Gaussian，也不修改桌面软件或真实项目。

## 文件

- `dist/index.html`：网页入口。
- `dist/styles.css`：毛玻璃设计与桌面/手机布局。
- `dist/curriculum.js`：14 课内容，按钮依据 2.0.0 当前源码。
- `dist/app.js`：课程、练习、搜索、进度与下载。
- `dist/model.js`：能量换算、参考、预检与安全存储校验。
- `dist/visuals.js`：SVG 曲线、分子模型与 Canvas 粒子。
- `dist/audio.js`：用户开启后的合成提示音。
- `tests/model.test.cjs`：针对科学规则与无效输入的自动检查。

## 检查

运行 `node --test tests/*.test.cjs`。页面布局和用户操作的浏览器验收见 `validation.md`。

本教程独立于桌面软件。桌面本机 WebEngine / 3D 的已知加载问题不会被教学演示的成功覆盖。
