# P1 第十六跑：UDATE 公共 sender 所有权修复集成与 BB 接收缺口

已集成经独立审查的 `client.c`、`test_client.c` 两份补丁，宿主协议和 USB 回归通过，模块、CPIO 与新 RAM 卡派生绑定均完成读回。**实际 guest 在首设早期出现 BB 异步发送失败断言，未进入拍摄 HUD；不能把本轮记成泄漏消除、P2 稳定或拍摄写卡通过。** 修复将未服务远端发送从虚假成功改为 `-1020`，暴露了原来隐藏的 BB 接收模型缺口。下一步需落实接收方的业务处理和消息所有权，不能恢复无接收方却返回成功的行为。

本轮仅在独立本机 QEMU 状态上执行一次，没有进一步委派，没有访问真实相机、物理磁盘或真实 SD。授权范围是集成既有候选、走既有构建/派生链、验证池和自然快门，并记录新前沿；未扩展到未经审查的新接收服务。本报告为工程验收记录，`flavor=null`，不涉及恶意软件或攻击归因。运行计划见项目内 `scratch/a7c2-capture-p1-runtime-20261115-candidate16/plan.json`。

## 集成身份与回退

候选为 `scratch/a7c2-udate-leak-20261115-candidate1/`，审查为其 `main-independent-review-v1.md`。应用前逐份执行 `patch --dry-run --fuzz=0`，备份和 SHA 映射保存在 `scratch/a7c2-udate-leak-integration-20261115/restore-manifest.json` 与 `restore/`。未覆盖其它产品源码变更。

| 输入/产物 | SHA256 |
| --- | --- |
| 集成前 `client.c` | `2734ff9e3e132d02027c19b9993a722e99c282f4408f4439cc045b272efeda44` |
| 集成后 `client.c` | `cddfadd8f9f827a7e2dddcc78d8f43bea7e9b25b6b01b50efd80fe3ff8456ba3` |
| 集成后 `test_client.c` | `ffeb05b8268bee3eac7092646918b6b56d16fef9a1843d95e6b41eef4b4595c6` |
| 构建/安装的 `sony_udate_distribution.ko` | `ceed736152244d57fe963606cf10a2c1975194b29a6ae8e4a1b4f086be42ec57` |
| 新 base CPIO | `2cdbf9f19cbc8be97dab143e23023bb4750c10aa40446c41a223e97bb7189948` |
| 新 RAM CPIO | `3c0a358dfd256c94f4acf5151968b46a4d37c406af427cce99c26ce36dd19292` |
| 新 derivation.json | `b68133223527cc3bafa4547a6446dfa3ba51370c6943fa22274f30d3e6acd5dc` |

使用产品 `report/virtual-cp/udate-distribution/build.sh` 交叉构建并安装 KO，再运行 `prepare-menu-initramfs.sh`。这次仅内核模块变更，复用既有 observer、DMM、声音 helper，未为无关 ABI 重建它们。CPIO 前后成员集合、权限均一致，**唯一内容变化是 `simulation/sony_udate_distribution.ko`**，见集成目录 `cpio-delta.json`。

生产 derive 使用同一只读 seed（SHA `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`），真实 fsck 经恢复 owner 协议运行，rc0、进程回收和 seed 身份核对均有记录。新派生目录为 `runtime/analysis/functional-camera-profiles/derive-prod-b422524259aacc5c/`。

当前产品保留本次集成及其**已知 guest 失败**，不是一份已通过启动验收的版本。需要回退时，以 `restore-manifest.json` 的逐文件原路径、前像 SHA 和 mode 恢复本次列出的文件，再按原构建链重建；不触及清单外的既有修改。旧 CPIO 和先前绑定均保留，不改写旧失败/成功收据。

## 验证结果

| 层次 | 结果 | 证据 |
| --- | --- | --- |
| 补丁、构建、ABI/安装读回 | 通过；KO 与候选完全相同 | 集成目录 `source-readback.json`、`build-module.*`、`final-sha256.json` |
| 集成模块协议 | 4 个 unittest 方法通过：57 个 UDATE/Backup/PCI case + 构建身份 | `module-tests.json`、原 stdout/stderr；第一次终端调用也通过，随后短重跑仅为保留原输出 |
| 宿主 USB 回归 | 2 组/2 并发线程，22 + 78 = 100 节点通过，无失败、无错误，源码稳定 | `analysis/scratch/cp-wait-20261111/usb-msc-host-batch-v4/run-34se4umf/result.json` |
| 新 CPIO 生产 derive | 通过，真实 fsck rc0 | 集成目录 `derive/derive-result.json` |
| guest RAM 卡完整 SHA | 两次完整读回与 seed 一致 | run16 `run-1-evidence/guest-seed.raw` |
| 新模块实际行为 | 观察到 `UDATE_K_UNSERVED ... rc=-1020`；早期未服务消息不再返回0 | 原 console；guest 内独立 KO SHA 因先发生断言未执行，不能冒记为独立 SHA 通过 |
| AP 启动/首设 | 失败：BB 原发送函数断言，随后系统错误 | 原 console 与只读 exception dump |
| 池长期稳定/三队列 outstanding | 未验证，没有取得可用的连续池样本 | `pool-analysis.json` 为空；`pools-initial.txt` 只有标记/符号信息，不能充作池数据 |
| ENTER_REC_STILL / Imaging 三 commit | 未观察到实际事件 | `event-proof.json`，排除了串口回显的 grep 模式文本 |
| 自然快门 / 4038 / JPEG / 写卡 | 没有提交快门；未验证 | readiness 前断言，`shutter-input.raw` 未产生 |
| mailbox/debugger/broker | 未接通 | `attempt-1.json` |
| owner 与退出 | QMP quit、rc0、租约保持到退出、runner closed、无信号 | `attempt-1.json`、`driver-exit.json`；PID 2121565/2122178/2122236 已退出，socket 节点无遗留 |

`assessment.json` 中早期子串统计含串口命令回显，例如 grep 语句内的 `ENTER_REC_STILL`、`4038`，**这些不是真实事件**。后续 `event-proof.json` 明确取实际日志行并给出否定结果，不回填旧记录。尤其 `FUNCTIONAL_JPEG_CODEC operation=enable` 只是组件启用，不是 JPEG 生成。

## 首错与缺失边

原日志的第一个业务断言为：

```text
assert at infra_wrapper_bb_ipsx_sp_pp_branch.cpp:978
function:void infra_wrapper_bb::detail::send_no_wait_with_main_thread_i(OSAL_ID, const void*, int32_t)
... notify_model_system_error(): Assertion `false' failed.
assert at infra_wrapper_bb_ipsx_sp_pp_branch.cpp:949
function:void infra_wrapper_bb::detail::send_no_wait_i(OSAL_ID, const void*, int32_t)
```

复用已有原函数语料 `analysis/appfw-decompile/corpus/parts/7/0x0034e0000.c`，ELF VA `0x34e521c`，其主线程异步包装明确执行：

```text
osal_valloc_msg_wait(0x92840747, ...) → memcpy → osal_set_msg_src
→ osal_snd_msg(0x92840747, message)
→ 若返回非零：报告源码行 0x3d2（978）并进入系统错误
```

本次没有重新生成反编译或宣称新增完整 CFG 核验；语料摘要已保存于 `event-proof.json`。该静态分支与本轮实际行978断言互相支持，说明 BB 主线程目的 `0x92840747` 的异步服务接受/处理/释放仍有缺口。通用 sender 对未知目的返回 `-1020` 会使这条非零失败分支可见。没有逐包原返回值/首失败 payload trace，因此不能直接指定是哪一个音频/BB 操作触发，也不能把邻近 `FULL_AUDIO_INPUT` 打印当作所有权已转移或业务已完成。

本轮还观察到未服务目的 `0x928708f7` 和不受支持的 UDATE reason=4 显式失败，均不应被当作已实现。候选只保留合法 UDATE 与已启用 Backup 的原路径；不能把这些显式错误改记为成功消费。

| Evidence | Finding | Path / 下一动作 |
| --- | --- | --- |
| E16-1：前后源码读回、KO 与候选 SHA 相同、CPIO 唯一成员 delta、生产 derive | F16-1：候选已完整进入实际实验输入，host 构建链通过 | P16-1：候选 → KO → base CPIO → RAM derive → FD/QEMU → 原 AP |
| E16-2：console 的主线程行978首断言 + 原函数 `0x34e521c` 非零返回分支 | F16-2：新的显式拒绝暴露 BB 远端服务缺口，guest 启动回归，置信度高；首 payload 尚未闭合 | P16-2：发送到 `0x92840747` → 非零 → 原 assert → 系统错误；下一步实现有证的接收与释放 |
| E16-3：零个可用池样本、零个实际 shooting/Imaging commit、未发送快门 | F16-3：长期池修复与 P2/P3/P4 验收受阻 | 接收服务完善后重新跑同一首设/池/自然快门判据，不能用候选合成压测代替 |
| E16-4：QMP 匹配 ID 的成功回复、退出 rc0、lease/runner closed、PID 与 socket 核查 | F16-4：本次 VM 已正常收尾 | 不重启、不发信号、不占用真实设备 |

## 复现与保留

已执行入口及原输出在项目 `scratch/a7c2-udate-leak-integration-20261115/`：`integrate.py`、`prepare-runtime.py`、`collect-results.py`、`finalize.py`。第十六跑入口为 `scratch/a7c2-capture-p1-runtime-20261115-candidate16/start.py`，复用第十五跑原驱动、37个 App32 首设动作和相同环境，只更新新派生绑定并增加 guarded 自然快门。脚本采用不可覆盖输出；重放须新建独立任务目录并刷新绑定，不能在原目录再次执行并覆盖收据。本次未对同一已定位失败进行无改动重跑。

集成/运行/新派生/原 run 映射/宿主回归的新增保留材料实占合计 **3,037,745,152B**（最终 ledger 写入前计量），实际文件回收 **0B**。计量时文件系统可用 **1,958,342,561,792B**；文件系统净可用变化独立记录，不当作本任务回收。完整账本为集成目录 `storage.json`，含路径、device/inode、逻辑长度、实占、owner、理由、下一消费者与回收条件；小型报告和最终账本自身不包含于前述瞬时计量。

保护项为前像回退、当前派生绑定、唯一原断言现场、原输出和不可变收据引用的原 run。下一消费者是主会话对 BB 接收链的核收及实现；只有替代证据/恢复材料接管并完成精确引用核查后才可回收可重建副本。没有仍运行的本任务 VM、租约或 socket；两个任务 tmp 目录均为空。未执行文件回收。
