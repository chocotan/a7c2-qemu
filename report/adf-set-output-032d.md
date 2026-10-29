# ADF set_output 032d：同实例格式、Monitor新B0与AVIO完成

`run-6_xlrsnt`已在修复后的a2eb observer/253冻结源与同一a0d候选上通过本阶段验收：原Common381释放132d `rc=0/faults=0/ap_consumed=1`，完整格式、Monitor新B0、实际event9和AVIO NoOp均有同轮内容证据。原Fsys两次flush0/STOP/恢复、目录全树摘要与clean commit也通过。`adf_set_output_native_verified=true`仅指本控制/元数据合同；原固件JPEG/MP4仍未产出，`capture_verified=false`。正式收据见[adf-set-output-native-proof.json](adf-set-output-native-proof.json)。

## 原运行请求和原CP路由

- 原Common tid381，目标92840747，动态source81cf61c4；source只能从实际allocator来源取值。
- 26B：`0d202d031a000180000001000101010100000000000000000000`。
- AP builder34ead94，发送34eb0d0:`17e9ff97`，等待12B回复。
- +8为LE16输出目标位图0；+10…17为I2S八项选择`01 00 01 01 01 01 00 00`；+18…25为HDMI/DP八项选择0。
- I2S顺序：48k/16bit/2、4、6ch；48k/24bit/2、4ch；96k/24bit/2、4ch；192k/24bit/2ch。它们是选择枚举，未恢复全部枚举名时不把0统一叫disable。

CP原件F5 SHA、VA−108000映射与其它ADF报告一致。`1c4992→1ca9d0`构造28B内层2004/0301，发9058003f，回送928407b9：

```text
042001031c000100
00000000 0100010101010000 0000000000000000
```

外层26B、内层28B、内部108十六进制容器是不同长度。getter666e3c返回`AdfSetOutputCtrl@121f488`；Ctor666e46初始化callback/busy/cache/FIFO。本包通过1774d4，冷态owner经1772c0→177678复制完整20B配置。`flags & 0x13f == 0`，路径1776be…c4→1776ea→666f3c→6667b0，不排AIP13b，也不进入独立1779f8的AIP-Off路径。

控制器20B缓存：`0000000001000101010100000000000000000000`。必须复制、读回全部20B，并更新第二个格式owner；不能仅检查位图0。

## Output/Power的实际已有状态与单NoOp

0323同一AVIO Output owner已消费三个stage，requested/current mask8、sourcecacheff、read/write/count=3/3/0。0336执行Input control0，不重建Output或清其shadow。

6667b0先control3读取Output+8/+c，实际为8/0。完整mask表达式包含SYSTEMSOUND的A/K/P/Q分支和bit3保留；当本包W=0且旧O=8时，目标恒为8。实现保留SYSTEMSOUND活动快照为未知，不构造“静音”状态，也不以未证明的SS字段作为准入条件。

同一Glee Input owner中的Power经70baa8构造，+20/+22均0、+14=2；前面0336 control0走已证明的相等快路，没有更改Power。零Power状态使本次control2**排队异步工作**：`(cached8 ^ target8)&0xf = 0`，仅一个type0 NoOp。原作业元数据：

```text
0000080000000000616f6600
```

read/write/count=3/3/0→3/4/1；70b9c8暂存mask/callback，70b9ce立即清Output+c。control3仍为8/0，不能将cache callback0误认作无作业。真实event9才pop至4/4/0，然后调用本地回调；回调内output_finished仍0。change0不写shadow，不重新执行三个stage。原666f61地址仅作来源元数据，实际派发为本地C函数。

## HDMI AudioMonitor：Notify1→Notify4→Notify2，必须有新B0

`1776a6→670e36`把20B格式另复制到`ProcHdmiAudioMonitor@1220de8+210`，再`670e52(reason2)`。该owner与Output缓存独立，不能遗漏。

Ctor `667c02→670c46`初始化mode0/path0、+204/+208、+20c…+240/+241/+242；`6710c2`生成双16B cache（+230/+244）：`00000000000000ff0000000000000000`。+243未证明赋值/读取，模型保持opaque unknown；本次宿主构造以A5作未知标记，不宣称它是原CP RAM内容，00/A5/FF不得改变行为。

| 实际父路径 | 原Monitor调用 | 关键状态和真正提交的工作 |
| --- | --- | --- |
| 0323 selector17c49a→6690fc，global3，登记Start前 | 6691a0→671278→Notify1 | +208=1、+240=1；13d全0参数→AF |
| notification0提交active path0 | 669248→67128e→Notify4 | 清+240；+242=0，转换/比较相等仍经671062提交B0(0,0)，清+208 |
| 当前032d完整20B格式复制 | 670e36→Notify2 | +240/+242=0；mode0 selectorff，转换first8相等仍提交**新**13d `{13d,1,0,0}`→新B0(0,0) |

原比较长度8（670fb8:`0822`），相等分支670fc0:`44d0`仍到671062。`51ffb4→b6fb60`向同一AIP buffer追加命令：

```text
b0000000100000000000000000000000
```

新B0必须重新解释、重新执行同一S0 disable provider的七笔写/读回。旧AF+B0的14笔为历史，本次累计应为21写/21读回；不能借旧成功覆盖，不能强置Monitor+240=1绕过工作。

## 实现与交接

权威代码在`runtime/analysis/device-models/`：

- `adf-hdmi-monitor.{c,h}`：一次构造、严格prepare(gen1)→commit(gen1)→configure(gen2)，完整格式和双cache，未知+243不进入谓词；实际emitter成功后才记录AF/B0提交。
- `adf-proc-device.{c,h}`：原routing_prepare/commit改由上述Notify1/4生产AF/B0，删除原重复routing cache；后续传递Output/Monitor/disable/command/clock的原引用。
- `adf-set-input-device.{c,h}`：只在原AP1336释放、worker/队列/订阅排空、ring9/9、原AB负历史仍在且Output control3=8/0时不可逆claim_output。复制的是引用描述，不是live device。
- `adf-aip-commands.{c,h}`：output_begin/enqueue/flush仅接收新source0 B0，唯一global event9执行；同物理ring9/9→10/10，新snapshot1/checked1/cursor3/task0，旧AB1/task0x1004及七条未检failure_snapshot字节保持不变。
- `adf-aip-disable.{c,h}`：固定限定第三次S0 disable，21写/21读回，active0400全部位保持；第四次和active callback等未支持工作仍拒绝。
- `adf-avio-output.{c,h}`：control3只读；same-mask NoOp沿用原60-ring/Output shadow，在event9 pop-before-callback；无shadow增量。
- `adf-set-output-device.{c,h}`：消费本26B、20B格式复制/读回、Monitor新B0、同Power/Output/clock、内外层完成与独立分配/释放。

时钟generation3与AVIO output generation2是不同的事务序号。`full_adf_source7_clock_continue_output`沿同一clock由counter/epoch8到9，不reset；仅一个真实guest timerfd到期，先AIP priority4新B0，再Glee NoOp。1ms为明确的独立虚拟策略，不声称原硬件频率/中断身份。

完成链`666f60→177fa4→177934`，666f2a清callback槽→178008；177738构造2004/8301/12。内层`042001830c00010000000000`经原decoder命名空间OR00580000，再由outer case1c515a/contextc5→69d1fc构造12B `0d202d130c00018000005800`。formatter不能脱离本轮实际完成固定成功。配置缓存保留，8301提交后才清原请求/busy。6ae14e/6ae198为日志路径，不构造appFw配置通知。

## 当前验证边界

新增38个真实0323→0336→032d宿主组合场景通过。修复四变量真实guest导出和console诊断后，全部相关父汇总为**342 passed/90 subtests**；既有analysis回归244 passed/1 skipped/58 subtests、脚本同步检查通过。独立源码审查未发现P1–P3，相关回归111项通过；重复覆盖不合计成新的唯一场景数。

主端点严格C11/Werror编译、纯模型严格C99/Werror及ASan/UBSan通过。原libc2.25下实际加载a2eb observer，constructor线程/API包装通过。253个冻结源逐文件摘要与归档内清单/当前已审源码相同，四个真实output API存在，测试API不在运行库。运行observer SHA256：`a2eb0acb8adb7195ab5c3cf6563cdc881320108498911c3f4ee94a5fd6db86b6`；本run归档SHA256：`8b898f578ebd890a0a924a18827c57fe5160e5821ee1c14b098f00e8168877b7`。启动会再次构建并压缩归档，gzip时间戳可改变归档字节摘要；始终以**同轮收据摘要+归档内253个文件内容摘要**核验。生产QEMU e235读回不变，运行候选仍a0d。

host/runtime manifest只记录意图，`adf_set_output_native_verified`仍保持false；运行消费另在本节和通过收据中证明。不能用合法profile代替实际端点启用与AP释放。

## 本轮内容验收：run-6_xlrsnt

证据原件为本run `console.log`、`runtime-manifest.json`、`observer-build-inputs.json`、`observer-build-sources.tar.gz`及`SD/export.json`。console SHA256为`40a4f479b346318a7df3632d371d0d3f5542aa6f05bdb48947f15177e0d24841`；完整摘录、行号、字段和断言结果在`adf-set-output-native-evaluation.json`，可用`runtime/analysis/scratch/evaluate-adf-output-native.py`重算本机保留证据。

| 证据 | 结论与实际调用路径 |
| --- | --- |
| E-032d-3：console1252原AP pid258的PROFILE enabled1/first_missing=none；12085原AP1336 free0 | F-032d-3：四个guest标记修复实际生效；P-032d-2先完成0336和原回复释放，再不可逆领原owner引用 |
| E-032d-4：12090请求与完整20B；12094–12097同依赖/Monitor新B0/3→4入队 | F-032d-4：完整配置和第二owner被消费，cache相等仍实际排新B0；未知SS和+243没有被伪造 |
| E-032d-5：12098真实timerfd到期1，observed46777727328≥deadline46777526672；12099–12101 | F-032d-5：P-032d-3同clock counter/epoch8→9，先新B0七写/读回累计21，再NoOp pop4/4/0并callback0；零shadow增量 |
| E-032d-6：12102内层8301，12105独立12B132d，12106 request free0，12107 Common381 reply free0/fault0/ap1 | F-032d-6：P-032d-4由本轮实际完成生成命名空间00580000，原AP实际消费元数据完成 |
| E-SD-3：两序号1436197763178794/1436198692448571，均accepted→before→after rc0→reply stored1，pid258/tid343/drive65 | F-SD-3：同run两次原Fsys flush/STOP/恢复成功，不靠stdout日志缺失推断 |
| E-SD-4：两export与host全树3文件大小/SHA全等、commit pending0/closed_pending0/transitions22 | F-SD-4：P-SD-1保存边界、宿主读回和普通退出闭合；不是图像或完整块镜像验收 |

本轮host树只有102B INPUT、9,670,656B database和406B mediapro.xml，没有JPEG/MP4。原TTS四帧创建/40B请求/epoch1/2与两次表读回强归属检查通过，外部Speech 8400/8401保持live，不释放/清零/重映射，不宣称global DMM idle。

后台任务正常exit0；host控制owner38107与其组均退出，无system QEMU，主锁和本card租约已实际独占获取后释放，无SIGKILL。独立只读复核da877c46确认原AP/raw/时序、全部253个源和34个关键initramfs成员、全部host三文件摘要一致，未发现P1–P3；锁获取与普通清理历史由主会话实际核验。GTK原始proof保留`ok=false`和`automation_completed=true`，因为它要求主会话审图且不声明完整相机实现；主会话核对原LCD HUD（J-FINE/14M/AF-S）存在、中央取景仍黑，不将其提升为拍摄证明。

原AP随后实际发出10B **set_mode 0110**：`0d2010010a0001800000`，同Common381/目标92840747/动态source81cf61c4。原AP detail::set_mode 输入实际两个u32为(2,0)，原转换后才编码尾部0000，不能当作无参数。CP工作、资源和正确状态域待源合同闭合；不直接复用00580000或raw0应答。Still/快门后EE仍1/0/0，group0 current2f/stop0/queued31→40；`capture_verified=false`。


## 运行负例：run-c2idzc8s

范围为本机隔离候选a0d、公开ALLLANG seed、独立256GB目录卡；不接真机或真实SD，不读private/full dump。b3c6 observer与253冻结源匹配，原AP再次释放1336 rc0/faults0，随后同Common381发出正确26B032d，但只出现旧`FULL_AUDIO_INPUT`，没有新端点记录。

| 证据 | 结论 | 后续路径 |
| --- | --- | --- |
| E-032d-1：本run console第12058/12059行、manifest与冻结源；摘要/raw摘录在`adf-set-output-native-evaluation.json` | F-032d-1：host profile意图已记录，guest实际constructor未启用，不能标native通过 | P-032d-1：host合法profile→guest export→constructor逐项检查→缺变量清enabled→旧fallback |
| E-032d-2：实际export含MENU_ADF_SET_OUTPUT，四个prerequisite无export；完整生成块AST与原constructor一致 | F-032d-2：缺MENU_BACKUP_SYNC、MENU_UDATE_DISTRIBUTION、MENU_DFS_SELECTOR、MENU_PIN_CONTROL_MEMORY | 在原output guard内传四个已由host验证的标记，保留全部准入；新增回归以实际完整export生成环境执行原C门禁 |
| E-SD-1：SD_ACK_BIND函数指针非空，应用stdout→/tmp/im.log→/dev/null | F-SD-1：本轮printf阶段诊断不可见；“没有accepted”不能证明Fsys未调用 | 改阶段/blocked诊断为直接/dev/console；Fsys消费者和STOP成功判据不动 |
| E-SD-2：retained-disk-evidence/preservation.json，QCOW1前后SHA相同 | F-SD-2：失败实例的匿名overlay和host树已保全，guest RAM cache未保全，仍非完整SD | 通过pidfd核验后普通SIGINT退出；GUI普通TERM/HUP、实际X2 socket绑定的Xvfb普通TERM；QEMU/组/双锁均释放，无SIGKILL |

本run两次SD请求均无reply、取消已挂起，原导出仍为`BarrierError: flush/STOP timed out`。GUI generation停在1546支持轮询饥饿假设，但不能排除某次flush内部等待；不因本次启用链修复而宣称SD问题已解决。负例与修复后新run分别入档，不回填成功。

## SD负例和待复验

`run-t558xqh9`的0336元数据成功与SD保存独立：flush/STOP超时，生命周期cancel_armed_no_reply；QEMU在恢复前已退出，guest cache和匿名overlay未保全。只保全3个host文件及摘要；自有GUI/probe/Xvfb/QEMU和双锁已释放，无SIGKILL。详见`adf-set-input-native-proof.json`及该轮`retained-disk-evidence/preservation.json`。

阶段/blocked诊断已改为直接/dev/console且保存errno；stdout=/dev/null、console open/write/shortwrite/close失败的回归通过。修复没有改变flush调用者、协议、超时、STOP/恢复或成功判据。`run-6_xlrsnt`重验两次原Fsys/STOP/全树/cleancommit通过，不能回填覆盖上述旧run失败。旧GUI/Fsys超时与032d等待的精确因果仍未证明。

`original_sd_export_verified_this_run_only=true`、`adf_set_output_native_verified=true`；原CP/硬件/PCM/图像帧/拍摄仍未验，`capture_verified=false`。
