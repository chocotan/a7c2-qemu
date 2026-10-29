# 全部13条图连接的原运行验收

`run-ouc1t64_` 已完成全部13条虚拟连接的原AP、格式消费及同轮目录SD验收。HDMI11与OSD12在同一运行中同时开启；不是把两次独立成功拼成联合成功。正式摘要见[13边收据](thirteen-edges-native-proof.json)，完整逐项证据在 `../runtime/analysis/menu-runs/run-ouc1t64_/all-graph-native-evaluation.json`。

**本次完成的是虚拟图连接、控制格式及原生通知消费。** `302c`尚未完成，EE仍为0，图像帧、JPEG、MP4和`capture_verified`均为false。原CP代码执行、页表、RTOS调度和原分配器容量也未验证。

## 本轮判据与结果

| 验收面 | 本轮结果 |
|---|---|
| 13条握手 | 13份独立56B完成回复，由原AP PID258/TID381、同原sender成功释放；rc0/faults0/ap_consumed1 |
| 旧1–10/13 | 旧DMM/格式映射、三份权威cache、NoMem/AB失败历史、Speech外部资源及各控制event保持 |
| HDMI11 | 64B原请求→64B peer0100→72B peer8100→56B AP8001；真实12B event6与保存的64B内容消费 |
| HDMI driver | 18B初始化、36B配置、job6/slot4/row0及12B完成节点实际保存、读取、释放 |
| UPM | 两笔16B原内核消息，真实U↔K映射、receive、`k_psave_api`分支、refcount/allocator和free返回完整闭合；kernel TID205 |
| 条件通知 | 两批各12笔20B通知，原`task_hdmi` TID349实际接收并释放24笔；按lease区分地址复用，不去重 |
| OSD12 | 独立unit e1700、16份持久资源、48笔DMM、16次双向SSOS消费；全部owners2/opens2 |
| OSD source post | 选中tag100 backing count改0，OSD缓存仍为1；没有额外通知/share/open |
| SD | 同轮两次原Fsys flush0、STOP/resume；两个导出和宿主3份文件的路径、长度、SHA相同，cleancommit |
| 收尾 | owner2233281、进程组及QEMU退出；主锁和该虚拟卡锁可同时独占取得、释放 |

UPM第二条原始operation为2，原内核规范化后的有效值为3。收据分别保存两份原始字节；没有把接收记录回写成原始3。对应原内核状态链表操作允许无操作返回，因此仅凭最终状态或send0不能验收；本轮直接观测了真实consumer及最终分配释放。

条件通知22次模型事件的发布未逐笔动态验收，本报告只声明已证明的24次原生receive/free。原用户接收函数位置已经由公开原件字节核对；当前console不保留所有receive-site日志，完整判据使用冻结observer中“原receive成功后观察”的接线以及每笔同receiver/TID的实际free记录。

## 数据与所有权实现

HDMI从constructor建立Initializing历史；三笔0102/0109/0127输入保留，0127中的动态payload SID是通知目的，不是原请求source。source gate从原构造写入建立，不在Connect时强置零。未完成真实消费前保留原AP请求，不发布成功回复。

UPM由专用内核线程消费，用户态free钩子无法直接观测。观察器使用本机私有Unix GDB服务读取原内核寄存器、指令和内存，按真实模块基址、原件摘要和relocated指令校验断点。唯一允许的guest写入是一个显式匿名4KiB数据邮箱中的256B收据：nonce、PID、lease、U↔K、原始/有效消息、真实kernel task/TID、consumer/free PC、refcount、allocator和free返回均受校验。它不修改原内核、硬件或ready位。

guest验证完整收据后只退休自己的账本，不二次free原内核已经释放的消息。邮箱页的PFN在发送前和收据验证后重读；`mlock`不被描述为万能物理迁移锁。观察器恢复GDB虚拟寻址模式，收据状态最后提交，正常detach后才结束；不使用SIGKILL。

OSD采用独立16×256B虚拟池，不借404池。所有格式含逐字节known mask，未证明字节保留`a5/known0`。creator在share/open后仍可修改同一backing，Open不增加owner。初始化没有逐通知close/free；Disconnect与active rows仍不支持。metadata_ready不代表GPE或帧ready。

## 测试与构建身份

本轮observer为 `898a0339c04a1fd6206e5069b66074cf041d797311098693600ef0d4cb08a1af`，321份冻结C/H/inc/sh输入。构建归档、实际源码和测试输入逐文件摘要相等；五份宿主入口和额外观察器/协调器源码也受摘要约束。12份原库、公开CP/ALLLANG、候选QEMU和完整选中initramfs均实际读回校验，生产QEMU未替换。

测试谱系完整保留：64模块2175项/139子测试的全量基线，随后两个消息生命周期窄修分别275项、276项相关回归；各级源码差分和测试日志SHA绑定原libc2.25 ABI收据，未将窄修测试称作一次新的全量运行。最终host观察器76项、HDMI内容验收41项、OSD内容验收67项、总验收传输/类型13项通过。

独立终审未发现已证实P1–P3：内存重放与原收据逐项一致，仅实时进程统计不同；321份输入、完整保留镜像中的原UPM/OSAL字节、22个UPM原始事件、13份AP回复、24条件、OSD资源及本轮SD/双锁均独立复核。另19个内存破坏反例全部拒绝。复核没有启动新VM、修改代码或发送信号。

独立审查发现并修复了最终唤醒丢失、收据日志发布早于邮箱提交导致过早停止、启动失败遗失unsafe清理句柄。原生运行还暴露了内核free后及用户free到send返回之间的地址复用；现按租约生命周期判归属，不凭地址永久认领消息。

## 日志和失败证据

原console SHA为 `bc3723e5915bef0ed73d87251504a5f685846913ad4ad89ad9340d29d9cf097c`，原文件未修改。宿主stderr在六处插入完整QEMU警告，另有一条完整guest DMM记录与完整host DFS记录相连。验收器只对固定整份原SHA、原始偏移、精确警告和两侧上下文恢复分帧：删除五份67B及一份68B宿主警告，插入一字节记录分隔换行，不补guest payload。解析后SHA为 `995393d193163828d24c2bbce3020d3f1b086818a396f6afa457c9f5e636ea26`；近似警告、错上下文和内容缺失均拒绝。

首轮OSD `run-rhvtidg2` 的内容与SD正向，但下一次启动重建了共享initramfs，旧整份镜像没有保留，因此保持未完整验收。随后独立重跑 `run-1xdwxzgj`并保留完整镜像，再执行本轮all13联合运行。此前HDMI各轮的CP表错误、调试通道/命名空间错误及地址复用失败均保留原结果，不用新运行回填。

## 复现入口

权威代码仅在 `../runtime/analysis/`。本机具备已验证公开资产、候选构建和原运行基线后，从该目录执行：

```bash
python3 -B scratch/run-hdmi-observed.py --all
```

该入口要求同一已测试observer和逐份输入摘要，继承完整公开Backup/目录SD前置链，同时启用HDMI11和OSD12。运行器在启动后立即保存完整选中initramfs及其manifest摘要。仅创建目录型虚拟256GB介质，不直通物理磁盘。

本轮离线完整验收：

```bash
python3 -B scratch/evaluate-all-graph-native.py run-ouc1t64_
```

若成功文件已存在，命令拒绝覆盖。只读重复核验可由独立review在内存调用`evaluate()`；所有固定构建和原始日志摘要仍须匹配。下一轮实际运行应生成新证据和对应精确transport pin，不复用旧成功文件。

后续工作从原`302c`成像启动继续，再推进CMOS/镜头/AF、帧、JPEG/MP4及独立解码；本次没有拍摄产物。
