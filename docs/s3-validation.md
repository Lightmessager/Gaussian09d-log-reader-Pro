# S3 验证与交付记录

完成日期：2026-10-15。范围为项目仓库、恢复服务与文件重连；生产 UI 在 S4 接入。

## 实现

| 文件 | 作用 |
|---|---|
| src/gaussianreadpro/storage/codec.py | 严格 JSON/模型解码、有限数值和身份/AST 校验 |
| storage/repository.py | SQLite v1 八表事务、修订/摘要、backup API、Save As、升级前备份与回滚 |
| storage/locking.py | Windows msvcrt / POSIX flock 持有型写锁，第二实例只读 |
| storage/recovery.py | 默认 1 秒防抖、显式 flush/关闭等待、独立恢复副本与状态、会话恢复 |
| storage/sources.py | 流式 SHA256、历史/当前状态分离、逐文件和目录重连预览 |
| storage/preferences.py | 独立 QSettings，本机语言/主题/最近项目/窗口等；Qt 惰性导入 |
| storage/portable.py | grpack 一致快照、自选日志、指纹核对与受限解包 |
| tests/test_storage.py / test_storage_sources.py | 数据往返、故障、崩溃、锁、恢复、包安全与偏好验证 |
| tools/check_s3.py | 不依赖已有 artifacts 的可复现存储全流程演示 |

未引入新的依赖；SQLite/线程/JSON/ZIP 只用标准库。QSettings 使用 S0 已固定的 PySide6。原脚本及 core 科学逻辑保持原样。

## 验证命令与结果

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe tools/check_s3.py
```

全量测试：**194 passed in 8.66s**；保留此前全部 139 项，新增 S3 55 项。标准库隔离检查在 python -S 子进程导入 storage，确认未加载 Qt、Plotly 或 NumPy。三个固定来源真实 G16 输出 dvb_sp/dvb_gopt/dvb_ir 的完整来源/作业/元数据/原文数值/行号往返相等；这些日志许可与指纹继续见 tests/fixtures/reference。

必要行为与证据：

- 两路径、共享节点、反向条目顺序、标签覆盖、原样无效草稿及保留 AST、别名 UUID、参考体系、单位版本、选中节点/页面/筛选/分栏/相机完整恢复。草稿恢复仍 invalid，不返回旧结果冒充新值。
- 三个写入阶段注入 disk full 类错误（清空后、来源后、提交前），均回滚到原修订；saved_revision 不前进，重试可成功。实际 SQLite BEGIN IMMEDIATE/EXCLUSIVE 锁冲突也验证失败与备份等待上限。磁盘满通过异常注入模拟，没有填满真实磁盘。
- 子进程在 before_commit 调用 os._exit(23)，再次打开触发 SQLite 热日志恢复，原项目全量相等，且进程写锁释放。另一子进程自动保存后 os._exit(24)，重开恢复出全部草稿状态。此证据为进程崩溃，不能代替断电/硬件故障测试。
- 同进程与跨进程第二实例只读；只读主项目的编辑可留在独立恢复副本。新请求在旧写入阻塞期间到达，关闭最终保存较新修订，无请求丢失。
- 恢复副本失败不虚报 recovery_revision，主项目失败不虚报 saved_revision；失败后保留 pending，可显式重试。恢复文件被占用、项目身份冲突、同修订不同内容均拒绝。
- v0→v1 在迁移前生成 SQLite API 备份，提交前故障恢复到原表/原内容/user_version=0，备份仍可读取；再试升级成功。v0 是机制测试用的预发布 JSON 表，不是已发布历史版本。
- 更新版本库/无关数据库拒绝且原字节不变；篡改节点 payload 被全项目摘要发现；非法类型/未知字段/重复键/深度/非有限数值/AST 拒绝。
- 移动整个项目相对路径仍有效；日志单独移动后保留原快照且当前计算失效；正确 SHA256 重连保持文件/作业/公式 UUID，文件改名也可匹配。同名不同内容拒绝、无 SHA256 不猜，目录多个同指纹候选报告 ambiguous。
- 项目搬迁后另存到新目录，路径重建且仍能验证来源；源库不变；精确 backup_to 不改数据。已有备份/另存目标拒绝覆盖，失败不发布半成品。
- grpack 有/无日志均可导入，附带日志在新目录通过指纹验证；原日志删除也能使用附带日志。manifest 明确列出本次附件，从已导入项目再次导出且不附日志也可导入，不从旧相对路径猜附件。声明附件丢失、路径穿越、驱动器、反斜线、符号链接、超额体积、日志指纹不符均失败，目标目录不留下半成品。
- EN、主题、窗口、最近项目等在独立 INI QSettings 中往返恢复；不会写入科学项目。运行时界面翻译不属于本阶段。

## 全流程演示

tools/check_s3.py 从合成 Gaussian 片段经 S1 解析，建立 R→TS1→I1→P，先验证 ΔE=[0,.024,-.008,-.025] Hartree。再创建第二路径、无效公式草稿、工作区和 3D 相机，保存 EN 偏好，关闭后精确恢复；随后移动日志/重连、另存、包导出/导入、保存失败/重试及迁移回滚。

本次 artifacts/s3/validation.json 的 passed=true、全部八项 checks=true；完整演示约 **713 ms**，含本机文件 I/O、哈希、QSettings 和多次数据库打开，仅作复现记录，不是 UI 性能承诺。

报告中的失败状态为 current_revision=3、saved_revision=2、recovery_revision=3、pending=true、error_code=storage_io_failed；重试后主项目与恢复副本都为 3，pending=false 且错误清空。报告包含运行目录、demo.grproj、portable.grpack、导入副本和迁移备份的定位信息。每次新建独立 artifacts/s3/runs/UUID，既有演示项目不被覆盖。

## S4 接入要点与边界

主窗口控制器以不可变 Project 为状态，先 revision+1 再提交 RecoveryService.request。表格按 UUID 绑定，不从显示行/名字恢复引用。读取 restore_session.calculation_project 作当前计算；snapshot 是历史证据，未连接来源的历史值须显式标注且不作为当前有效导出。

仓库/恢复 API 同步返回；虽由执行器独占连接，UI 仍须用后台任务调用，避免等待 I/O/扫描/关闭阻塞事件循环。启动依据 LocalPreferences.last_project 与 list_recoveries 给出恢复选择。关闭检查 service.close() 状态并处理保存失败，再关闭主仓库。别直接丢弃错误或把 recovery_revision 显示成主项目已保存。

本机仅验证 Windows；POSIX 锁/标准路径提供实现，macOS/Linux、网络共享、断电恢复及成品 GUI 退出流程仍待各自阶段实测。生产 schema 为 v1，后续升级须新增明确迁移并保留故障验证。S0 固定演示界面保持原样，本阶段没有声称已完成成品 CN/EN UI 或恢复对话框。
