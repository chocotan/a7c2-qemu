# 第二十五跑：4037 实际消费通过，重复 4023 触发单笔保留限制

4037 候选已独立审查、精确集成并完整重建。实际 guest 中，同一原 AP 线程的两笔 4037（selector `0x12`、`0x4`）都更新 still token、执行虚拟 focus intent、释放原请求，`request_free_rc=0`，没有 AP ACK、CP 完成或 interlock 绕过。原先的 4037 路由缺口已解决。

**本轮运行仍失败**：原 AP 随后第二次发送 4023，既有 remainder 单笔保留槽尚未退休，模型返回拒绝，再次触发 Imaging3109。未进入首设/HUD，三条 Imaging commit 为0，mailbox/broker、自然快门、JPEG 和写卡均未验收。没有继续扩展 4023 后端，也没有删去 pending 守卫。

范围是审查→集成→第二十五跑；无进一步委派、真实设备、物理 USB 或相机写入。沿用 direct-bootin AP 诊断路线，使用虚拟 CP，不执行原 Sony loader/WBI、原 CP RTOS 或完整冷启动。历史已通过结果不自动计入本轮。

## 审查和部署

[独立审查](../../../../scratch/a7c2-cp-4037-20261115-candidate1/main-independent-review-v1.md)确认生产入口为 `menu-observe.c:osal_snd_msg → full_imaging_functional_dispatch`；旧 legacy dispatcher 没有该生产调用者，前置 capture dispatcher 仅处理4038，不截获4037。候选复用唯一 functional 状态 owner、mutex、仲裁和 focus-intent helper，没有启用旧私有路径。

[独立复验](../../../../scratch/a7c2-cp-4037-20261115-candidate1/checks-review1/summary.json)为2线程、2组：88项新增场景、320项既有 imaging 场景、严格和sanitizer旧协议所有权程序、AArch64交叉编译均通过，产品冻结输入未变。覆盖原wire尾部 `ffffffff`、全部 selector、包长/来源、403d同owner、busy/capture/pending205b、live-reply重叠、重入、fork、并发与receiver free失败；未发现需candidate2修正的P1/P2问题。host通过不替代guest执行。

只集成候选清单中的四文件：imaging-device C/H、新C fixture、新pytest入口。按before SHA保存恢复前像并完整读回，先 `git apply --check` 后应用，after SHA均匹配。其余既有产品修改保留。`build-observers.sh` 重建快照内imaging-device、menu-observe及所有依赖对象；随后 `prepare-menu-initramfs.sh → production derive`，真实只读fsck通过既有恢复owner执行。CPIO只有 `simulation/menu-observe.so` 内容变化，成员和权限保持，KO未变。

| 产物 | SHA-256 / 身份 |
| --- | --- |
| preload | `e0cb64da294408e3587efddcb3f1bd2f98ebd3b941611907774ea88b03f23bbb` |
| base CPIO | `a2bc9e99190a3257d6b0e762c5f88bf8b18842806a4afabb6a31cb90b35ea72f` |
| binding | `derive-prod-107bfe1bccc85f82` |
| derivation.json | `1f396850ddc75679af43c4ebb96670ecd192cc4c1b0e70f0ade67f10fe7439ee` |
| RAM CPIO | `d03cae57a374dc17eba058e7a8d9bf5253acbd08ec22725bb03bba12a6584bda` |
| KO | `b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5` |

[集成目录](../../../../scratch/a7c2-cp-4037-integration-20261115/)保存脚本、原stdout/stderr、退出码、源读回与CPIO差异。产品回归2线程、2组：imaging **408 passed**；CP **7方法、100 subtests**；UDATE/Backup/BB **6方法、69 subtests**，另CP40b8六场景、BB0159五场景均通过。脚本沿用的logical_scenarios字段不替代实际计数，不把方法、subtests和场景简单相加。USB未变，未重复其重型回归。

## 实际原 AP 的执行与下一前沿

[运行目录](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate25/)对应原run `runtime/analysis/menu-runs/98a8`；归档与原日志逐文件完整SHA一致。guest读回preload/KO匹配部署；1GiB卡与 `/image_mmca` 的全卡SHA均为生产seed `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`。卡副本读回不等于原Fsys挂载，后者本轮未验收。

下列为原console按LF计数的物理行，CR删除不增加行。[运行汇总](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate25/runtime-summary.json)与[前沿核验](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate25/frontier-readback.json)保留同一口径。

| 行 | 原事件 | 证据支持的行为 |
| --- | --- | --- |
| 7681–7683 | tid451 sequence12，4037，selector12，token8000000a | `still_token[0x12]`更新、controls=1、slot_written=1、free0、retained0、ap_reply=none，requested/effective均04000000 |
| 7684–7686 | 同tid sequence13/403d lock1 | functional interlock继续工作，requested变04008000 |
| 7689–7692 | sequence14/4022/32B | 原wire进入新保留槽，handler/apply/completion仍0 |
| 7693–7696 | sequence15/4023/12B，token8000000d，body2 | 一笔4023被保留，`backend_missing=config-gates+central8306` |
| 7697–7699 | sequence16/403d unlock | requested恢复04000000，原请求free0 |
| 7706–7708 | sequence17/4037，selector4，token8000000f | 第二笔still token更新、controls=2、free0、无ACK，interlock仍04000000 |
| 7709–7711 | sequence18/403d lock1 | requested再次变04008000 |
| 7714–7717 | sequence19/4023/12B，token80000011，body2 | 同目的90030001、源80020002；模型记录 `remainder-pending-or-owner-fault` |
| 7730–7733 | ASSERT_CALLER / lib_assert.cpp46 / Imaging3109 | 第二笔4023之后触发原系统错误 |

两笔4037仅记录**虚拟意图**：`CP_D012_verified=0 physical_ASIC_verified=0 capture_verified=0`。它们没有使AF ready、清启动inhibit或输出拍摄完成。接收free失败的保留地址和sticky fault路径已有host覆盖，本轮没有触发。

4023的第一笔与第二笔wire分别是 `050023400d00008002000000`、`050023401100008002000000`，仅token不同。部署源码 `preserve_remainder()` 的守卫明确包含 `remainder_pending[index].pending`；slot无业务完成/退休出口，所以先前保留状态足以触发拒绝。该分支调用 `unsupported()`，将result设为 **-1021**。这是原wire、pending/拒绝日志和精确部署源码共同支持的返回值；没有独立 `P18_OSAL_RESULT/4023/rc=-1021` 行，因为被模型直接处理的发送不经过底层send-trace。运行汇总中 `first_negative_send=null` 仅表示该trace没有观测到负返回，**不表示所有发送成功**。

首设工作流已预置37个原App32动作；首个系统异常后驱动停止输入。HUD/三连接守卫未成立，未发快门，也未执行捕获门禁读回。守卫后快门代码已核对 `SHUTTER_HALF=0x1f1`、`SHUTTER=0xa7`，使用原half/full/release序列；`capture_gate_readback.py`仅只读观察，不写gate或伪造ready。此次失败发生更早，无必要重复相同运行。

## 下一步与恢复

Evidence → Finding → Path：两笔4037成功free且同原AP线程继续后续命令，证明functional接线有效；首笔4023 pending与第二笔同body拒绝绑定单笔保留限制；下一工作应实现4023的实际config gates、central8306分发和消费者退休/所有权合同，或先从已恢复的原CP语义证明安全的接收/应用/释放子集。不能仅清pending、扩大永久保留容量、吞掉第二笔请求或制造completion。4022/4028以及其它保留族、0118/0159/0500后端仍有独立缺口。

恢复前像在集成目录 `restore/`：目录0700、文件0600，manifest记录原路径、原mode与完整SHA，已逐文件读回。父会话确认无消费者后可按before SHA恢复两份C/H并移除两份新增测试，再沿同一构建链重建；或恢复已验证旧preload/CPIO与对应收据。旧binding和唯一失败未修改，未执行回退。

## 生命周期与空间

QEMU pid2368978/starttime126848093已退出，launcher不存在；runner closed、disk lease保留至退出、QEMU rc0、无信号，driver rc2保留业务失败。QMP唯一quit ID `86a5662b4774f865139164caa81599c6` 的实际响应是同ID `return:{}`，原wire SHA匹配。原run无socket/FIFO，`/proc/net/unix`无该run引用。

[收尾审计](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate25/final-audit.json)与四目录storage账本记录主要新增/保留实占 **3,018,956,800 B**，实际回收 **0 B**；采样可用 **1,931,854,053,376 B**，满足64GiB余量。集成前可用1,934,912,651,264 B，文件系统净变化单独记录。st_blocks口径含恢复前像和当前derive，reflink共享块可能重复计数，不等同底层独占新增；后续小型脚本、独立复验和报告由final-supplement补记，账本自身不递归计数。

**未执行回收**。当前binding、恢复前像、原失败与检查重放产物保留供父会话核收；下一消费者为4023后端/退休实现。可重建检查品须父会话接管后，经精确身份与活引用核查再回收，保护原失败和必要恢复。没有遗留运行VM、租约或socket。
