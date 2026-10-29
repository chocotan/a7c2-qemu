# ADF set_input 0336：公开配置消费与元数据完成

当前完整控制后端已在`run-t558xqh9`验证原AP实际消费`1336`回复；
host组合/profile为 **207 tests / 139 subtests通过**，原libc 2.25 ABI与247份冻结源码吻合。
本轮GTK/SD整体验收失败：flush/STOP超时；尚无JPEG/MP4。

范围是公开ALLLANG 2.01、隔离native QEMU、默认关闭的独立虚拟后端。
原CP、音频硬件、PCM、帧与拍摄标志保持false；AB的已知失败单独保留。

## 启用与前置

显式选择`A7C2_ADF_SET_INPUT=virtual-input-s0-v1`，guest对应`MENU_ADF_SET_INPUT`。
需要既有Backup/UDATE/background/touch/TCIN/DFS/NoMem和
`A7C2_ADF_PROC_PATH=virtual-source7-idle-v1`完整前置链；入口拒绝未知值或漏前置，不自动补齐。
协议标识为`AP0336-type0-input-config-S0-v1`。

只有原AP已经释放`0323`回复、所有工作/队列排空且资源guard通过，才能交接原有
HotShoe、Glee、AIP命令缓冲和source7时钟。同一实例不复制、不重置、不重复初始化。
`full_adf_proc_claim_input()`将该交接作为不可逆的单次业务；后续不回放AF/B0。

## 原请求、路由与回复

`run-kao1n0qd`与`run-rujerqv8`都在`0323`原AP消费后实际发送：

| 项 | 原字节/值 |
|---|---|
| 请求 | `0d2036030e000180000200000000`，14B |
| 目标/source | 92840747 / 动态原AP caller |
| +8…+12 | type0 / channel2 / samplingRate0 / bitDepth0 / delayChange0 |
| +13 | 本轮原字节0，relay不读取 |
| AP候选链 | 34e5788 ← 34f2bec ← 34c6ec4 ← 339d6a8 ← 33aaa3c |
| 内层请求 | `04200104100001000002000000000000`，16B |
| 内层完成 | `042001840c00010000000000`，12B |
| 外层成功回复 | `0d2036130c00018000005800`，12B；原Common381已实际释放rc0/faults0 |

CP原件SHA256：`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，
文件偏移=CPVA−108000。appFw SHA256：
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。

原AP builder34f2abc、调试名4c68190=`adf_set_input`；34f2be8发14B并等待12B，
34f2bec读reply+8再34e349c转换。内部87可更新cache，但外层339d6ac仍要求0，不用135冒成功。
CP wire0336→eventce→relay1cb758→9058003f/`AdfSetInputCtrl@121e8a0`。
最终69d4de构造1336，1c78e0独立分配/复制/发送，不能就地修改原14B。

## 原完成与异步错误分离

原663fd2顺序为：139排AD/AB/AE → 131 → Glee control0回调 → 141/102/110。
冷态Glee callback173288实际写status/+ac4并进入1733d0。
本type0、数字麦克风配对标志+ac9=0时，按status0提交四字节cache、排日志及内层8401，
返回后才排102。因此原元数据完成不等待AIP所有命令成功。

AB只接受共享S1/S6，本后端保留S0：AB返回status1，不写C008/C00C。
原b6d1c4字节`41f20400`明确为`movw r0,#0x1004`（十进制4100）。
67a11a调用AIP task后，67a11c:`0220`显式覆盖返回值，scheduler67d29e调用后直接递增槽位；
该异步错误不传给本次Glee完成。禁止把AB改成0，也无需为了外层元数据完成强造S1。

独立虚拟策略保守延迟对AP公开回复，直到配置数据工作、回调和本次四次实际调度结束。
这项延迟不是原固件等待AIP全成功的条件；`hardware_audio_success`仍为0。

## 冷态owner与已完成的原运行

HotShoe ctor67c336给current_type0/busy0/FIFO10空。
本次先实际注册回调，再出队更新read/count，在busy1中调用；回调返回后才提交type并清busy。
旧type80/8的异步电源分支不在当前支持域内。

Glee Input ctor70b2c8…b300给type0/source1/callback0、kind缓存0和空50-ring；
Power ctor70baa8给flags20/21/22=0，state14=2。
原0323 control30仅改driver14/18，Output目标8不会改变这些Power字段。
因此本次control0 `[0,0,1,callback]`满足原cache相等分支，真实同步回调，不排三stage、不改缓存；
control1读回0/1/0。其它状态保持拒绝，不能强写状态选择捷径。

`run-rujerqv8`以observer
`89628487c071dc84eb73d9b7fa08321c11f00ee5c0545e6fbdeac814686d9a0d`、240份冻结源码
实际证明：事件前一次构造，事件4原control30/31排空后同实例记录历史，原Common381释放0323回复rc0/faults0。
原Fsys三文件全树读回、cleancommit、owned进程/QEMU退出、双锁可独占均通过，无SIGKILL。
收据：`adf-input-cold-owner-native-proof.json`。这轮没有执行新的0336后端，不能回填其消费标志。

## 公开Backup、selector2与配置数据

固定公开seed SHA256为`3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`，
CP record偏移ed000；host完整SHA与两条BK4 checksum仍是准入条件。

| key | 文件偏移 | 值 | 用途 |
|---|---:|---:|---|
| 690219 | 14d1b9 | 00 | 输入owner4c0、Abb65c0/6601 |
| 690227 | 14d205 | 00 | 原195e20结合capability word8=1得到Init selector2 |
| 690228 | 14d206 | 00 | Abb bb0/c00与opcode11 feature0 |
| 6902a8 | 14d298 | 00 | owner98条件，当前保留0 |
| 6902f1 | 14d2e1 | 00 | Abb相关配置域 |

capability word7=0、word8=1分别用于格式准入与selector，不能混用，也不能把5e028a20直接当selector。
原描述符表e90cc8：839项×12B，总跨度42b；前393B涉及310个属性，其中6个attr2仍保留原值。
362B可从公开Backup重建；31B空洞未知。模型存A5 canary/known0，掩码访问只读取真正需要且knownff的字节。
mask外零是数学投影，不能宣称未知RAM为零；失败不改输出和查询数。

源码`adf-public-config.c/h`复用同一次全seed pread/FNV循环，
`adf-aip-backup-map.inc`只包含362项源/目标偏移布局。
完整owned视图＋known mask重新计算FNV`5a1ab318aea2e5f8`，元数据或字节被改即拒绝。
静态证据为`runtime/analysis/menu-runs/tcin-tests-20261025/adf-input-backup-view-static.json`。

本次template为1116fd0，40B SHA256：
`727818f44b2198889d61fc78b6a1fb776154883cfad72bd39fed81d892c29f07`。
02命令为LE32 `{2,44,payload[9]}`：

```text
08080100 20011ff7 14141414 14090814 15141414
15141416 14141416 00000000 43211121
```

`adf-aip-input-config.c/h`在owned S0/active0/cold-cache0上，03先真实重应用缓存，02再实际合并九字，
消费calibration/masks并逐项写/读回f48a2000…23ac的独立寄存器bank。
两次共222写入/222读回/131次公共读取；保持未触碰寄存器及2100的掩码外位。
03分类2008/200c=3/3；02路径2060…6c=0/1/8/8，分类0/1。
完整ROM表及摘要在`adf-input-config-rom-tables.json`；不是物理MMIO已恢复的证明。

## 共同命令、ring与失败快照

固定九命令：AD、AB0、AE0、B8=0、03=0、02、11、B6=0、B7=0；
body132B/33 words，另8B批次头。复用已完成AF/B0的同一owner和缓冲，不重建历史。

76-slot response ring保留一空，容量75。九条都实际解释，AB失败不停止command cursor。
随后整批复制到snapshot，ring read一次推进到write；consumer只检查AD0、AB1便返回0x1004。
`checked=2 / cursor=6words / uninspected=7`保留失败快照；七条不留在ring。
后续真实调度发布新count0快照，不能说补查了旧七条，也不能擦掉失败历史。

source7同一owner从generation1的counter4/epoch4继续；getter不tick，
四次真实guest timerfd到期产生generation2/sequence5…8。1ms是明确虚拟控制策略，不是原MTG频率。

## Kikilog与所有权

663ecc是目标811006e9的20B kikilog参数更新，不是appFw音频配置通知。
SID0284、非对齐u32 sublogid2111、非对齐flags81000000，payload为原cache `00 02 00 00`及四个明确零。
最后两字节原producer未赋值，本后端明确选择零padding：

```text
8402112100000000008100020000000000000000
```

保留allocator实际source，不伪设92840747；发送成功转交kernel，不再由用户释放/解引用。
分配或发送失败按原best-effort合同记录；临时消息只按自身owner清理，异常清理失败保留现场。
原kikilog内核线程先复制20B再osal_free_msg；只有记录开启且param_set规则匹配才更新参数缓存。
当前未观察kernel free或缓存匹配，所以`parameter_consumption_verified=false`。

## 测试、失败证据与当前边界

定向组合/profile：207 passed / 139 subtests；配置模型、队列、clock与cold owner包括ASan/UBSan。
日志：`runtime/analysis/menu-runs/tcin-tests-20261025/adf-set-input-composed-and-profile-tests.log`。

组合测试曾发现helper把0x1004误写成十进制1004；父独立解码原Thumb后修共享常量与错误fixture，
并增加原指令立即数独立回归。修复前输出保存在`adf-set-input-before-taskcode-fix.log`，不回填通过。
完整失败矩阵还区分临时reply清理与原caller消费，不把一次free混成另一项。

## 原运行 run-t558xqh9：元数据消费通过，SD失败

observer `c436488ca210509efe0ee03fc2e5b007718bf80034ece0ee58c2089e35c89f6a`，247份冻结源码，
同一a0d候选，生产e235未替换。worker1053实际消费公开393B视图、完成222写/读回，
write_hash=`5426b1385bec3f14`与host golden一致；四次真实guest到期继续5…8。
AB1/0x1004、首snapshot9/checked2/cursor6/七条未检历史均保留。
原AP PID258/Common381释放独立1336指针，rc0/faults0/retained0/ap_consumed1；请求free0。

随后原Common实发26B `032d`：
`0d202d031a000180000001000101010100000000000000000000`。
元数据接口消费收据：`adf-set-input-native-proof.json`；逐内容判据在
`runtime/analysis/menu-runs/run-t558xqh9/adf-set-input-native-evaluation.json`。

本轮`SD/export.json`为`BarrierError: flush/STOP timed out`，生命周期`cancel_armed_no_reply`；
原Fsys flush、SD导出均未验收。QEMU在恢复前已退出，匿名overlay和guest dirty cache未保全；
只保全宿主目录3文件并核对摘要，不是完整虚拟磁盘或拍摄成功证明。
所有原错误、GTK proof false及损失标志保留于`retained-disk-evidence/preservation.json`。

QEMU已退出后，对匹配本轮的GUI发TERM/HUP、Xvfb及孤立probe仅TERM，
全部自有进程组/QEMU/双锁已释放，无SIGKILL。原保留控制目录列在收据，未假装所有文件已删除。
下一步恢复032d真实AVIO配置并调查/复验SD barrier，不补写ready或跳过flush。

`input_metadata_native_verified=true`；`original_sd_export_verified=false`、
`ee_verified=false`、`capture_verified=false`。
