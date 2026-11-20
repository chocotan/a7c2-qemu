# P1 第十九跑：40b8/0159 已接收，下一发送缺口为 402a

本轮完成独立候选审查、测试消费者修复、产品集成、完整preload/KO重建、CPIO、生产derive与宿主回归。实际guest已执行新的40b8参数接收并释放请求，原BB0159发送返回0；同一Imaging线程随后发送402a返回-1020，再次触发原3109。不能称3109已修复；本轮BB949未复现，也不能以此断言整个BB业务完成。首轮发生异常后停止输入，未进入HUD，未发送快门，mailbox及拍摄写卡均未通过。

授权来自父会话的三段委托：审查候选、必要修复后集成、第十九跑；禁止进一步委派、真实设备和对QEMU发信号。沿用现有direct-bootin诊断路线，原CP固件未执行，不是整机冷启动/WBI验收。原样例及历史失败均保留。文档按docs-generator，flavor=null；相邻tool-index缺失，无新增工具依赖。

## 审查与最小修复

[独立审查](../../../../scratch/a7c2-cp-40b8-bb-0159-20261115-candidate1/main-independent-review-v1.md)核对最终diff、完整handler、调用顺序及原字节合同。运行实现未发现必须修改的P1/P2；发现P2测试消费者缺口：产品旧`legacy-40b8`仍要求委托。candidate2改为`parameter-40b8`，验证接受、无ACK/分配、一次释放、u32值和pending读回，保留全部其它旧case。新检查采用显式失败返回，没有增加assert。

候选代码保留严格边界：40b8仅接受type5/12B/source80020002，u8[+8]零扩展到u32[P+170]，记录common APPLY pending，不执行apply或发ACK；0159清bit4，保存原u16及12B VDF2001:0302快照，lower_sent=0/applied=0；0118仍保留请求和pending_mask=3，不发1118。free失败保全、fork拒绝、cp302c history失效与未知命令拒绝路径均保留。

[原字节独立核验](../../../../scratch/a7c2-cp40b8-integration-20261115/source-verification.json)通过8项及256个signed-byte分支变换；CP身份SHA256=`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。只读取原文件，没有运行CP。

## 集成与验证

[集成目录](../../../../scratch/a7c2-cp40b8-integration-20261115/)保留前像、逐文件SHA、fuzz=0 dry-run/apply、全部原stdout/stderr。只应用三份运行源码diff及两份测试消费者修复；候选out-of-tree checker路径不带回产品。新增CP40b8/BB0159 fixture按原路径消费当前产品。

完整`build-observers.sh`重建所有guest对象与KO；CPIO成员/模式不变，仅`simulation/menu-observe.so`、`simulation/sony_udate_distribution.ko`内容变化。生产derive真实执行只读fsck与恢复owner协议。恢复到本轮前状态应按`restore-manifest.json`逐项验证前像后恢复，并走同一preload/KO/CPIO/derive链，不能只回退KO。

| 输入/产物 | SHA256 |
| --- | --- |
| 新preload | `1f01bad3c986a87ba0d479c312d5ca6885031a24ed25196d53a96ef8aa442843` |
| 新KO | `b4733732904b00641e7bef9900decffb090f5756389f977afe10ecd1c1ea21ab` |
| derive binding | `0fc7cf629beec5df08d82c1ee908459c33a6bd9c60633c63a97750d3ede3149e` |
| derive RAM CPIO | `8b5971089dcd9332a5a6eaa0faab3473203eb19ee76674707b997327af20ba54` |
| QEMU | `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad` |

生产binding位于`runtime/analysis/functional-camera-profiles/derive-prod-2f347f3d59ec56fc/derivation.json`。

宿主验收分组与线程分别记账：产品2组/2线程，CP/history为3方法、100 subtest，kernel为5方法、69 subtest；新增CP6与BB5场景（BB包含65536个u16全遍历）通过。既有USB runner另外2组/2线程，22+78方法及39 subtest通过，来源稳定；原收据在`analysis/scratch/cp-wait-20261111/usb-msc-host-batch-v4/run-7eu_dojw/`。这些host结果不替代guest或CP业务验收。

## 首轮实际运行

原run为`runtime/analysis/menu-runs/0962`，映射及完整归档在[第十九跑目录](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate19/)。guest全1GiB卡SHA和生产seed一致，产品源码稳定；新preload和KO在setup中实读SHA。尚未建立broker，因此transport总状态仍failed，不能由卡SHA推导Fsys同卡或sealed memfd。

原console中的顺序（行号为首轮原文件）：

| 行 | 观察 | 能支持的结论 |
| --- | --- | --- |
| 7218 | 0118/22B send rc0 | 请求被接收；不代表LCD/EVF已应用或1118完成 |
| 7224 | 40b8 generation1、value0、apply_pending1、free_rc0、completion0 | 参数写入及接收所有权出口执行；未完成apply |
| 7229 | tid463、402a/12B、source80020002、send rc-1020 | 下一明确未支持命令 |
| 7230 | `infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109` | 原Imaging断言仍存在，对应新的402a拒绝 |
| 7246 | tid441、BB0159/10B、raw value7、send rc0 | 原0159发送不再因目的缺口返回-1020；VDF后端未验证 |
| 7251–7252 | `notify_model_system_error` | 固件异常，停止按键，未尝试快门 |

首轮没有BB949。UI初次导出返回空帧，未得到有效OCR；原程序虽创建28个widget，不能认作已显示可交互首设页。一次获准重试仅提高诊断内核日志级别并纠正trace筛选前缀；产品、binding及原按键路线不变，重试失败独立保存。

重试原run为`runtime/analysis/menu-runs/eaeb`，[独立核收](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate19/retry-runtime-summary.json)确认：0118实际worker日志为generation1、selector3、pending_mask3、request_retained1、applied0、completion0；0159实际worker为raw_value7、generation1、lower_value7、lower_pending1、lower_sent0、applied0、completion0，随后`BB_K_CONSUMED command=159 accepted=2 freed=1`。pending和释放边界均按候选执行，没有虚构1118/VDF完成。402a仍由同一发送线程返回-1020，随后原3109及系统断言复现；没有BB949、ENTER_REC_STILL、三连接commit、mailbox或快门。

两轮原console SHA256分别为`50eb98191fb04a57d6111f710effb854c8eb727d75bcde5574f9e9d9b07f70ce`和`fcdc5089234f93cb24af2bd67149cb78f1a3d580705820b9f2c477be5da4cdd7`，均与归档完整读回一致。summary中的行号使用规范化text splitlines；上表为原LF行号。两轮QEMU均实际quit/rc0，driver因固件异常正确返回2；无信号、owner进程已消失、runner关闭且租约保留到退出。异常后串口边界未知，额外异常命令被拒绝并保留原收据，没有为了继续输入绕过边界。

## 待闭合前沿

下一实现对象是402a的精确CP合同及消费者；不得为消除断言泛化接受整个4000命令族。40b8 common APPLY、0159 VDF0302、0118 LCD/EVF/1118仍缺后端。首设走图、ENTER_REC_STILL、三Imaging连接、mailbox、P3快门、JPEG及P4写卡各需新的实际证据。

| Evidence | Finding | Path |
| --- | --- | --- |
| 原字节核验+产品源码读回+新build/CPIO/derive | 40b8与0159准确接收候选已进入实际输入组合 | 静态合同→限定handler→完整重建→guest身份读回 |
| 首轮40b8参数接收与0159原send rc0 | 两处旧目的缺口推进；不代表下层完成 | AP原send→模型接管→参数/pending/释放→真实后端待接 |
| 同tid402a rc-1020紧接原3109 | 首个明确新发送缺口为402a | source80020002→90030001/type5/402a→原错误处理 |
| owner实际quit/rc0、无信号、租约退出 | 失败现场保留，运行资源按合同退出 | 停止输入→唯一QMP id→quit→wait→退租 |

空间及最终两轮owner收据见本轮[final-audit.json](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate19/final-audit.json)、`storage.json`与`finalize.json`。封存时本任务新增/保留实占约3,041,157,120B（约2.83GiB，含完整恢复前像、新derive、两轮原现场/归档及host收据；末尾小收据写入另占少量块），实际回收0B；项目盘可用1,951,363,899,392B，远高于64GiB余量。文件系统净变化不记作本任务回收。

当前derive是下一轮真实消费者输入；前像供产品回退；两轮原失败和pytest生成的边界fixture源码/二进制供父会话核收，均有明确下一消费者和回收条件。恢复副本逐文件SHA核定并保护为目录0700、文件0600，原模式留在manifest。已核无本任务存活VM、socket或FIFO；未执行文件回收，未访问真实设备。原运行输出保留于scratch/受管menu-runs，不复制入公开报告目录。
