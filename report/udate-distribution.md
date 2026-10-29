# UDATE reason-1 分发边界与虚拟 round-trip

## 结论范围

当前自然启动链在 `sequence_clock` case1 内进入原 kernel 日期 SET，并等待
`udate_wait_for_distribution_done`。这不是仅由静态反编译推测的候选点：被动 `/proc` 内核栈已直接
显示该调用链。尚未证明补全此分发后一定完成clock、mode transition、EE或拍摄。

本文同时记录一个**显式、默认关闭、非原CP执行**的虚拟远端实现。它不能替代原CP固件，不能证明
硬件ready，也不能把虚拟状态有效或type4发送本身当作guest业务完成。生产实现位于
`report/virtual-cp/udate-distribution/client.c` 的 **kernel public sender**；用户态C模型只保留为
协议参考/单元测试，已从生产observer移除。

## 动态证据

### run-v_605ywl：请求方用户栈

无ptrace passive采样在 `SeqQueueCommon` 自身同时找到：

- AP `0x36ecab0`、`0x306e624`，对应reason-1 SET及其case1返回点；
- `libosal_udate+0x2ef4` receiver；
- `+0x2f5c`、`+0x41ec`、`+0x3d34` 调用路径；
- **`+0x3ebc`**，直接kernel日期SET的返回点。

因此执行已经进入kernel SET，不是仅停在AP同步消息封装或本地MWF/semaphore。
`UDATE_ASYNCSET` 的独立futex idle是另一线程，未被冒充为该同步路径。

### run-ou4e0ac5：请求方内核栈

`ee-passive-suz52t9o/thread-359-kernel-stack.txt` 直接记录：

```text
osal_wai_sem_tmo
udate_wait_for_distribution_done+0x74/0x148 [udate]
udate_get_localtime [udate]
udate_set_date [udate]
udate_proc_read_clock [udate]
udate_read_clock [udate]
```

同轮 `CLOCK_SEQUENCE sequence_id=0x83 case=0x1 flag_44=0`、clock无序列依赖等待和group0
current=`0x83` 与此前一致。采样只读 `/proc`，没有SIGSTOP、ptrace或业务状态写入。
原日志的 `No snd_msg registered. Skip snd to 0x5c5` 与该等待相互印证，但接收端形状仍按原代码
核验，不仅凭错误字符串实现协议。

## 原协议恢复

### kernel发送端

原 `udate.ko` 中：

- `udate_get_localtime+0x1c` 向 `0x3e9` 发送同步时间请求；
- `udate_get_localtime+0x50` 调 `udate_send_date(1)`；
- `udate_distribution_send_each@0x2390` 构造44字节消息，type=1，reason=1；目标表 `.data+0x1b8` 为0、1，
  0跳过，实际 destination 为 **`0x909005c5`**，source/base 为 `0x809005c5`；
- `udate_send_date+0xa0` 调 `udate_distribution_send_ready`；
- 完成后才进入 `udate_wait_for_distribution_done`。

### 原分发线程

`udate_distribution_thread@0x1d00` 的消息循环、type1处理函数 `0x1988` 及type2响应wrapper
`0x1b98` 给出以下顺序：

1. 接收type1，读取原sender当前日期/时区并记录timer；
2. 向sender发送type2查询；查询的 **body `+0x0c`** 是动态回复queue，OSAL source为
   `0x809005c5`；原 `udate.ko:0x1b98` 回复wrapper从body `+0x0c` 取destination，不能只
   把queue写在OSAL source；
3. sender经 `osal_snd_sync_direct(0x910042)` 读取原kernel timer，并回复44字节消息：
   - `+0..3` type2；
   - `+4` status；
   - `+0x10` date；
   - `+0x20` timezone；
4. 分发端再次读取timer并计算 `(after-before)>>1`；
5. 更新分发端独立date/timezone/elapsed；
6. 最后发送type4，唤醒原发送端。

**type4不是对type1的空ACK。** 它位于真实查询、响应验证和接收端状态更新之后。原
`udate_distribution_done_notified` 从接收到的source的bit28..30选择目标；本地虚拟投递因此
使用target1 `0x909005c5` 作为type4的接收侧source身份，确保通知target1而非target0。
这不是声称恢复了原CP所有发送前地址重写规则，而是复现本机原接收端所需的身份。

## `virtual-roundtrip-v1` 实现

文件：

- `report/virtual-cp/udate-distribution/client.c`（生产kernel模块）；
- `runtime/analysis/device-models/udate-distribution.c/.h`（用户态协议参考，不注入生产observer）；
- `A7C2_UDATE_DISTRIBUTION=virtual-roundtrip-v1` → guest `sony_udate_distribution.ko`，
  manifest协议为 `kernel-public-roundtrip-v1`。

首轮 `run-38y7a1k_` 证明用户态接入边界错误：`NATIVE_UDATE_*` 为零，原kernel仍报告
`Skip snd to 0x5c5`，因为type1由 `udate.ko` 在内核直接发送，LD_PRELOAD无法看到。该轮还因
`--host-sd-dir` 未被旧GTK脚本消费而实际使用128MiB RM卡，不能作为目录SD或UDATE协议失败
证据。kernel模块和显式目录SD admission是为这两个独立问题做的修正。随后 `b35c7db53` 又在5秒内
因新增launcher提前使用未初始化 `base` 而退出，仍不是协议或拍摄负面结果；该错误已修复并有
启动前回归。

模型只接管destination `0x909005c5`、source/base `0x809005c5`、44字节、type1/reason1且
**body `+8==0`（异步）** 的已分析请求。自然reason1由 `udate_distribution_send_ready`
以sync=0发出；body `+8!=0` 的同步请求需要另一条同步回复协议，直接delegated，不能接管后
让原发送方等待其 `+0x0c` 队列。其它目标、类型、reason、尺寸或源地址记录有界
`UDATE_K_UNHANDLED ... original_default=1` 后保持原默认路径。kernel public sender只注册一个
端点；若已有其它public owner，注册失败并让启动失败，不抢占或伪造成功。
它要求同一自然启动profile中的 `virtual-mode3-cold-v1`，避免把boot前置3007缺口误当作独立UDATE实验。

一次round-trip：

1. 调原 `osal_snd_sync_direct(0x910042)` 取timer-before；
2. 经原 `osal_dynamic_id(0x2a)` 建动态回复queue；
3. 经原 `osal_valloc_msg_wait/osal_set_msg_src/osal_snd_msg` 发type2，body `+0x0c`写动态queue，
   OSAL source写base；
4. 以5000ms上限等原AP分发线程的type2响应；
5. 验证尺寸、type、**32位status**、date和timezone，消费原响应并释放动态queue；
6. 再取timer-after，保存**虚拟远端**的date/timezone/elapsed；
7. 最后经原OSAL发送type4/reason1，并以target1作为接收侧通知source；
8. 正常释放原type1请求；失败时保留并锁存fault，不做不安全的强制unwind，后续请求拒绝。

错误、超时、无效响应、busy、fork以及done发送前的资源失败均不发送正常完成。type2已发送但
响应未完成时，动态queue保留，防止迟到回复进入已释放queue。所有fault都会锁存，拒绝后续伪装成
正常的新完成。唯一需要单独区分的是：type4已经成功发出后，原type1的free失败会保留请求并记录
`request_free_rc/request_retained/faults`，这条记录不是clean completion，也不能据此宣称clock完成。

### 明确不是

- 不是执行 `cpapp-b.bin` 或恢复其真实远端状态；
- 不是host生成时间、host截图或独立文件注入；
- 不是硬件ready、CP全功能、clock完成、EE1或camera capture证明；
- 不是写 `udate.ko` 完成slot、调用waiter wakeup、修改sequence/current对象或伪造model写。

## 当前验证与待验收

主机侧已用ASan/UBSan和 `-Wall -Wextra -Werror -pedantic` 验证：

- 正常type1→type2→响应→type4及状态；
- 不支持形状delegated；
- timer、queue、allocate/send/receive、status/date/timezone/size、响应free、queue free、
  done allocate/send等失败均不产生正常完成；
- 原请求释放失败保留并可重试；
- 响应保留、busy和fork保护。

当前主机验证分为两套：用户态协议参考为 **2项测试、21个子测试通过**；kernel client为
**2项测试、15个子测试通过**，另有launcher/probe/observer组合回归和AArch64模块/observer构建。
kernel测试覆盖真实body+0x0c路由、target1、32位status、短缓冲、同步delegated、分配/释放ID、
超时、queue/发送/释放故障、原请求保留和busy。独立审查发现的问题已修复；启用UDATE时要求
`selected_observer_matches_build=True`，GTK在输入前还等待 `UDATE_K_REGISTER: rc=0`。
上述均属于主机实现验证，**还不是新的kernel VM运行验收**。

下一次隔离QEMU验收必须同时检查：

1. manifest和GTK实际profile绑定；
2. `UDATE_K_REQUEST/QUERY/RESPONSE/DONE` 的真实kernel OSAL流量；
3. type4只在有效响应和虚拟状态更新之后；
4. 原case1是否返回、clock是否完成、group0是否越过 `0x83`；
5. `sequence_mode_transition::run`、EE下层、拍摄/JPEG/Fsys分别重新取证；
6. SD原Fsys导出、host提交、flush/owner恢复和进程/lease清理。

若任一后续边界仍未到达，应保留为新前沿，不把UDATE round-trip本身提升为照片或视频成功。

## 2026-10-25 kernel VM实测：run-bh0ryvgh

`b4d205550` 使用 fresh host directory、真实 `A7C2_DIRECTORY_SD`、固定
`directory-vvfat-256gb-v1`（256000000000B）、CP3007和本profile。`runtime-manifest.json`
核对了observer、initramfs、kernel模块和receipt的同一SHA；GTK在任何输入前实际看到
`UDATE_K_REGISTER: rc=0`，并打印 `DIRECTORY_SD_PROFILE_BOUND` 与
`UDATE_DISTRIBUTION_PROFILE_BOUND`。

这次不是host mock：原kernel串口依次记录一次完整round-trip：

```text
UDATE_K_REQUEST  destination=0x909005c5 source=0x809005c5 bytes=44 reason=1 async=1
UDATE_K_QUERY    destination=0x809005c5 reply_queue=0x809061c8 timer_before=65925912
UDATE_K_RESPONSE generation=1 date=2023-01-01T00:00:00 type=0 timezone=0/0 elapsed=363 status=0
UDATE_K_DONE     generation=1 target=1 done_source=0x909005c5 timer_before=65925912 timer_after=65926639 elapsed=363 request_free_rc=0 faults=0 request_retained=0 done_sent=1 virtual_completion=1 hardware_ready=0 camera_capture_verified=0
```

因此模块已在原kernel public-sender边界消费type1，完成实际type2查询、timer读取、响应
接收/校验、虚拟远端更新，再发送target1 type4；不是空type4，也不是主机生成时间。原
`Skip snd to 0x5c5` 不再出现于该reason-1路径。另一条早期reason4记录为
`UDATE_K_UNHANDLED ... original_default=1`，仍按范围delegated。

### UDATE之后的真实前沿

`CLOCK_SEQUENCE` 仍只留下一次case1入口记录，不能把entry count当成clock完成证明；但
`ee-passive-4w6j930v` 的后UDATE Common栈已不再含此前的 `0x36ecab0/0x306e624/
0x306f54c` 返回点，而出现 `0x34e5788/0x3470458` 等新候选。原sequence名称表解析为
`0xbe=sequence_set_touch_panel`；raw stack尚未正式unwind，名称表也只提供静态ID映射，
因此这是多个返回候选与原调用链交叉支持的最强下一前沿，尚需entry/worker观测确认，不能直接
宣称已测得group0 current。机器码/反编译链为：

```text
0x3470328 (sequence_set_touch_panel::run)
  -> 0x34c6158
  -> 0x34e8b00
  -> 0x34e552c(0x92840747, request, 10, response, 12)
  -> osal_rcv_msg_tmo
```

该请求为 `200d:0146`，不是UDATE或EE。它解释了UDATE完成后新的同步等待候选；本次没有
后续 `MODE_SCHEDULE`、transition run或EE启动证据，EE仍为0，不能宣称整个group0或
拍摄链已恢复。原 `uipc warning ret=-1022` 与CP3006 delegated记录也保留，未改名成UDATE
失败或伪造其完成。

### 失败收尾与证据边界

GTK在首次截图前遇到guest命令返回1，后台达到360秒超时；没有自然快门、JPEG或MP4。
`SD/export.json` 保持 `ok=false`、`flush/STOP timed out`、`cancel_armed_no_reply`，所以本轮
**没有**原Fsys flush、owner STOP/CONT、clean host commit或目录SD导出通过。console没有
原SD mount/write/commit记录，host目录仅有未变的诊断 `INPUT.BIN`；据此仅授权一次正常
SIGINT做无数据清理，未宣称保存成功。QEMU、父进程、GTK和Xvfb随后均退出，host逐字节
不变，锁/租约释放，未使用SIGKILL。原始失败proof/export不改写，详见
`menu-runs/run-bh0ryvgh/udate-evaluation.json` 与
`directory-recovery-shutdown-assessment.json`。

下一步仅针对 `200d:0146` 的原始接收方、响应布局、状态/readback和ownership做 bounded
调查/实现；不得用通用ACK替代。直接请求、CP `0x1146` 回复和F02F未知项见
`report/touch-panel-frontier.md`。UDATE kernel集成与round-trip已通过本run，但自然启动、
clock全量完成、EE、liveview、照片和录像仍未验收。
