# 大步骤 6：从菜单改值到新进程恢复

这篇解决有限参数提交、完整 Backup 导出和实例发布，不保证所有 SID、首次设置完成状态或跨 VM 时钟都持久化。

变量见[索引](README.md)。本次只读公开报告和实现，未读取任何设备私有 Backup。

## 小步骤 1：分开原参数、内存值与文件值

**问题 →** 界面已改值，不知道是否已提交到文件。
**现象 →** 同一轮原 API 读语言25/日期2，文件却可能是25/3，也可能已经25/2。
**误判 →** 两项都必须和文件不同才能同步；或者文件存在就算保存完成。
**定位 →** 核原 getter/setter 的 ELF、PLT/GOT 与实际指令，再比 API 与目标记录。

| 参数 | 属性 ID | SID/尺寸 | 公开 seed |
| --- | --- | --- | --- |
| 语言 | `0x02cf0401` | `0x02cf`，1B | 1 |
| 日期格式 | `0x02cf0403` | `0x02cf`，1B | 3 |

**解决 →** 实验 helper 不含 setter，只读并在需要时调用公开 `Backup_sync_subsystem`。
真实原 GUI 的简中/月-日-年以高亮与 API 现场25/2确定，不靠菜单序号猜。
**剩余 →** 两项提交时序不一致，不应为制造 pending 而补假 setter。

## 小步骤 2：返回 0 后继续看写入闸门

**问题 →** 同步返回0，完整文件却未变。
**现象 →** 单改 `Backup_save=1` 的旧对照没有得到目标记录提交。
**误判 →** 把 `Backup_save` 当全局保存总开关；静态看到跳过分支就说找到旧失败根因。
**定位 →** 原 `backup.ko` 是 ET_REL，地址按 `.text+offset` 与重定位解释。
helper 比较 Overwrite/Temporary 两套记录：均找到、尺寸匹配才复制并标候选。
没有候选也可返回0，候选非零才进入原 `backupfile_save_file`。
**解决 →** 历史 owned 硬断核指针、尺寸、候选和保存参数；实际该轮候选为1，进入保存。
因此排除的是“本轮走 no-op”，没有追溯替旧失败指定原因。
**剩余 →** 候选不是已证逐字节 dirty 位；到保存调用也不等于完整文件已经导出。

## 小步骤 3：完整文件与双 bank 一起验

**问题 →** 小记录匹配，不能代表导出的是一致完整 Backup。
**现象 →** 旧 helper 因不认识合并 memrsv 布局在导出前拒绝，原同步可能已成功。
**误判 →** 将导出失败算成原保存失败；把 WriteComp 整个 u32 必须为1当规范。
**定位 →** 分开同步、文件结构、保留 RAM 窗口、跨通道读取四阶段。
**解决 →** 核完整2390264B、双 bank/checksum、目标字节与二次 API 稳定。
有限 SID51 案例的 bank0大小968981，bank1从970752起、大小1419512。
WriteComp 实见 `0x101/0x100`，旧 C helper 只检查低字节；高位语义不猜。
完整文件经 guest FNV/RAM/QMP，再用 guest OpenSSL独立 SHA 和 host 全文件 SHA 对齐。
**剩余 →** 双 bank 校验有效只证明结构和所取文件，不能证明全部参数提交覆盖。

## 小步骤 4：把恢复观测放在正确时间点

**问题 →** 新 VM 中记录读回正确，晚些时候全文件 SHA 却变了。
**现象 →** 原应用启动期间可能合法提交别的内容。
**误判 →** 要求 post-app 全文件永远等于源；或只因两个值相等就认为来源正确。
**定位 →** pre-app 同阶段核完整文件 SHA、目标 API 与两个实际 seed；post-app另记变化。
**解决 →** SID51 有“不依赖 powerseed 的原 API 恢复”有限证据。
语言/日期另从真实 GUI 25/2 文件恢复，先核原值，再运行只初始化 SID51 的启动上下文 helper。
原用户字段没有由 setter 重写，新 app 正常启动后再读25/2。
**剩余 →** 一次禁用启动上下文后的 abort 保留；对照差异不单独证明其唯一原因。

## 小步骤 5：正常快照与“新提交实验”使用不同成功条件

**问题 →** 两项已被原固件自然保存，实验 helper 仍报 no-pending。
**现象 →** FAILED 文件实际 API/file都25/2，双 bank有效。
**误判 →** 为让实验变绿而删 no-op 保护，或信任任意 FAILED 文件。
**定位 →** 区分“本次 helper 证明新提交”与“正常关机获取一致快照”。
**解决 →** 新提交实验保留 no-op 拒绝；snapshot 允许值不变或已保存。
只有 API/file不同时才同步有限 SID，再核全部输出；失败记录不回填。
已自然提交的失败文件作为恢复输入前，额外核精确失败原因、无 sync、原 GUI改值与全部摘要。
**剩余 →** 整体 false 可保留有限有效证据，但必须另写限定 review，不能覆盖原结果。

## 小步骤 6：用稳定实例、租约与 CAS 防止“保存到了别处”

**问题 →** run 临时目录无法承担跨整个 UI 进程的配置身份。
**现象 →** 新进程可能重用旧环境变量恢复源，或并发发布覆盖较新一代。
**误判 →** SD 已保存就是配置已保存；`current.json` 丢了就自动回默认 seed。
**定位 →** 原配置源、实例目录、generation 与实际 cpio 两个 seed要能互相追溯。
**解决 →** 生命周期持同一实例租约，load严格校验；不可变代保存完整文件。
OFF顺序为配置snapshot→SD保存→配置CAS发布；失败保留VM。
发布前写/读回/fsync，再原子替换 current；旧 expected generation 拒绝。
宿主内部恢复变量先清除，只由租约/store生成本次恢复输入。
**剩余 →** 指针替换后的目录fsync失败可导致 PublicationUncertain，不能盲重试或宣称旧代仍current。

```bash
# 执行目录：$PKG；只读查看保存事务、CAS和不确定发布处理
cd "$PKG"
rg -n 'PublicationUncertain|generation|fsync|reset' runtime/analysis/setting_store.py
rg -n 'snapshot|restore|lease' runtime/analysis/settings_instance.py
```

## 小步骤 7：关掉整个 UI 后再核一次，重置也要走生命周期

**问题 →** 同进程 ON/OFF 成功不能排除 Python 对象缓存补值。
**现象 →** 本包后来实际原菜单改25/2，关整个 GTK后新 GTK仍读回25/2。
**误判 →** 默认1/3的保存轮替代真实改值；新窗口出现就算恢复页视觉通过。
**定位 →** 检查实际选用cpio两seed唯一且同源SHA，原 API/file和实例代相符。
**解决 →** 本包有限跨进程改值恢复通过；真实确认框reset发布逻辑墓碑，保留旧代和SD。
reset仅在停止、安全清理和租约条件满足后执行，成功才再启动。
**剩余 →** 第二 GTK截图过早，只证明机身窗，未计重开后原页面视觉复验。
首设完成状态仍未保留；“销毁”是逻辑重置，不是历史数据安全擦除。

## 解决了什么，仍未解决什么

原 API→原文件→完整校验→宿主代→新进程新VM回读，已对有限参数闭合。
没有把完整文件备份称为全部 SID 都正确提交，也没有承诺异常退出零丢失。
原 SIGTERM 中断导出的失败保留，其信号唯一来源仍未知。

## 证据入口

- [no-op、实际保存分支与双 bank](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/backup-noop-sync-contract.md)。
- [真实菜单保存/恢复与实例接线](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/user-settings-progress.md)。
- [CAS、权限和不确定发布合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/setting-store-contract.md)。
- [本包独立补验及其视觉局限](../../validation/README.md)。

## 如果你在做别的机型

Backup双bank、SID与属性格式需要重新逆向，不能套用偏移或WriteComp数值。
可复用的是改值→提交→内容校验→不可变代→新进程原getter的验证链。
把快照、恢复、重置和SD保存当不同事务，明确每个失败点的保留行为。
