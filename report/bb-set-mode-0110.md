# BB set_mode 0110：032d后的实际等待

`run-42_4pb06`已在25eff observer/263冻结源和同一a0d候选上消费本次BB `set_mode 0110`：提前构造的虚拟source-image状态沿86个已准入前驱保持word1，本次wire更新operationMode0，1760B数据/掩码复制与双级work完成，两次内部21a只发布一份独立1110；实际原AP释放该唯一reply指针rc0/faults0/ap_consumed1。当前run的原Fsys两次flush/STOP恢复/全树3文件摘要与退出双锁也通过。收据见[bb-set-mode-native-proof.json](bb-set-mode-native-proof.json)。这是控制/元数据与本地虚拟工作验收，原CP/硬件模式/图像帧/拍摄仍未验，`capture_verified=false`。

范围为本机隔离QEMU、公开ALLLANG AP/CP原件；不接真机/真实SD，不读private/full dump。EE仍1/0/0、无JPEG/MP4，`capture_verified=false`。前一阶段的metadata/SD通过见[032d收据](adf-set-output-native-proof.json)。

## 已有证据

| ID | 原件/证据 | 结论 |
| --- | --- | --- |
| E-0110-1 | run-6_xlrsnt console12107原AP132d free0；12108实际0110；console SHA256 `40a4f479b346318a7df3632d371d0d3f5542aa6f05bdb48947f15177e0d24841` | F-0110-1：前沿由本轮实际消息确认 |
| E-0110-2 | appFw.so SHA256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`；字符串VA4c6a818/4c67eb9及builder34e7b74 | F-0110-2：API为infra_wrapper_bb::detail::set_mode；原输入不是空配置 |
| E-0110-3 | 同轮两份thread-381-stack.txt；SHA分别`c30512f4b641e34d95e6407d1083a2c73fa1882806cb21a1cdd26723b4a21323`/`6adacff62d37517bbf111423e259ba5ea8f418779bc903c96a788b1e37f0778f` | F-0110-3：请求、(2,0)和原BL后返回PC同存，支持当前同步等待；不是正式unwind |
| E-0110-4 | cpapp-b.bin 18,090,880B，SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`；CPVA=raw+108000 | F-0110-4：路由、任务与原始result回复已静态闭合；当前状态历史和选中子任务仍未知 |

主会话另行按AP ELF64 PT_LOAD映射验证4个BL及完整builder摘要，并按CPVA−108000验证6个原Thumb/表项锚点。可复核原件为`runtime/analysis/menu-runs/bb-mode-tests-20261026/bb-set-mode-0110-static-pins.json`；它只证明原字节，不证明当前BB状态或任务执行。

## AP输入和等待

原字符串为：

```cpp
void infra_wrapper_bb::detail::set_mode(
    const infra_wrapper_bb::set_mode_in_t&,
    infra_wrapper_bb::set_mode_out_t&)
```

源文件名为`infra_wrapper_bb_ipsx_sp_pp_branch.cpp`。调用路径P-0110-1：

```text
33aaa38 → 339d44c (ENTER_REC_STILL)
339d918 → 34c5998 → 34e7b74 → 34e552c
34e5784 → 原osal_rcv_msg_tmo
```

关键BL字节：339d918:`20a00494`、34c59c0:`6d880094`、34e7c80:`2bf6ff97`、34e5784:`6fe48597`。完整builder `[34e7b74,34e7d34)` SHA256为`2b423f6816bc4f41b7768f9e1bfa81c494a40e2d16b4e1d55b34c679a77653a3`。

builder先清包体2B；第二输入0/9/15时，第一输入0/2/3/4编码body0=0、第一输入5编码1、第一输入1 fatal；第二输入4保持0，其它未支持值fatal。本轮原对象+f724/+f72c给出的值为(2,0)，不恢复未知枚举名。同轮栈中请求地址7f37f6f900、原输入地址7f37f6f9f8。

候选原返回PC链为`34e5788←34e7c84←34c59c4←339d91c←33aaa3c`。两份syscall/SP/PC边界相同，仍保留`current_blocker_proven=false`。AP期待独立12B回复，复制全部12B、在动态调用者queue释放后，将reply+8交`convert_bb_err_code@34e349c`。该共用转换器支持多个状态域，不能仅凭AP兼容raw0判断CP应回何值。

## CP事件、共享状态和真正模式任务

CP转换器1c5300把0110映射到event19：表项1c540a:`8701`→1c56f8:`1920`。该case至公共尾部不读请求+8/+9；生成28B框架信封，type0/event19/动态source，原请求指针仅在入口r3==1时带入+10。它不是2004 ADF内层wire。

执行owner为`InfraBB::Function::ExecModeHandler`，RTTI d16cc4→cd1f20，vtable d16ca8:`e5161c00`→1c16e4，event19表项1c1758:`8e03`→1c1e42。已核成员接线：R=1ff3ba8、H=R+38，69b200→69b190构造H，69af04→69b234设置H+4=R+fac、+8=R+50、+c=R+64、+10=R+808、+14=R+1468。链接状态69ddf4清其+4整字（故byte+5/+7初始0），执行gate 69b29e置byte+4=1；它们均与BB singleton分离。

共同动作：调用69de82清所连状态对象byte+5，置byte+7=1，然后经6a3dd4→6a3dde读取`10efa3c.word0`。其32B文件初始化为`[1,0,0,0,0,0,1,0]`；真正setter6a3e46保存旧word0至+18，调用1d8cb0(event)，写新word0并更新+14；6a3de6只写+4。不能从文件初值、链接flags或`cp_cold_control.model_mode=3`推出当前singleton状态。首0110前16条候选前驱报文已提取到`bb-0110-predecessor-wires.json`，其状态更新链仍在核对。

| 实际状态word | 原result | 新任务target |
| --- | --- | --- |
| 1 | 0 | 3 |
| 3 | 0 | 4 |
| 5 | 0 | 5 |
| 6 | 0 | 6 |
| 7 | 0 | 7 |
| 2、4及范围外 | 1并记录错误 | 不排该任务 |

成功分支先保存共享配置+68到17890fc，再69de28(target)。69de28经69525e取得任务owner1788ef4；1db10c按值复制20B descriptor，再写+18 target/+1c 0，共发送32B。当前槽的已知布局为PMF code(+0)=69dea3、PMF adjustment(+4)=0、work(+8)=1aaddd、附加字段+c/+10=0；**+14…+17是未初始化栈间隙**，保持未知，不要求零。第二个零字不是context。

第一队列为CP RTOS task30/queue3，静态ring0x2800，max_message32，每条含4B长度头占36B，容量284项，另有已出队in-flight项。1db198消费者先复制到稳定栈项、归还队列空间，再把`&record+(adjust ASR1)`作为PMF的this。当前adjust0，因此调用69dea2；该thunk读取record+8的work，把target移为r0并尾调1aaddc(target)，**没有外部完成callback**。work返回后才进入下一次receive，返回值不被保存；队列为空不能证明没有in-flight工作。1db10c发送timeout0，满返回false/-50；69de28丢弃bool仍返回0，wrapper0不能证明入队。

work1aaddc通过69adac取得live配置01ff34c8，在semaphore5保护下把**0x6e0/1760B**复制到独立snapshot01ff2cc8；关键1aadfa:`4ff4dc62`为mov r2,#6e0、1aae02:`73f004e4`调用memcpy。然后按target选work，经1ab99a…1ab9b0向第二owner1788f14提交新32B记录，PMFcode695405/adjust0、work为chosen，arg0=01ff2cc8/arg1=0。第一层返回只证明第二层提交，不等于子任务完成。

已定位target3→1b37ed、target4→1b33c1、target5→1b3709。子任务的operationMode由6986da读取017890fc；它在首completion已入队后才由ExecModeHandler读取live+68并经6986e6保存，不能与系统状态、target或AP(2,0)混为同一值。

**条件性有限路径已闭合：target3且operationMode0**，1b3806:`002d`/1b3808:`3ad0`跳到1b3880，直接新提交699556(0110,0)并返回0，不读40B旧流、不open/close ClkCtrl、不调用VSignal、不进入1bdbf4、不重置流状态。target4且operationMode1同样可走有限快路。它们均须真实执行两级任务与1760B复制；实际实例是否满足上述条件仍待状态/配置历史核准。

其它组合不能套快路：target3非零mode可能open ClkCtrl、VSignal/真正模式工作；target4/mode0先close ClkCtrl，依赖017891e0/旧流与系统谓词，并可能进入1bdbf4，之后6988a2还会重置两组流快照。1bdbf4的非即时路径设置completion位图003e，调用输入/输出/格式/音频等消费者，逐位完成才提交最终通知。现有ADF工作不能替代这些消费者。

### 共享配置与本次operationMode的真实生产

live配置01ff34c8，快照01ff2cc8，恰为1760B。6996b0初始化段明确写live+68=0（6996ec:`a566`），原启动1d0ab8:`c8f0faf5`调用该初始化；它不是BSS零推断。该初始化段有1565B明确来源、195B未写入，未知范围为：

```text
000–003 025–027 058–05b 064–067 108–17f 181–183
1a8–1ab 1c1–1c3 1cd–1cf 239–23b 24e–24f 29d–29f
2a9–2ab 2d2–2d3 2de–2df 2e9–2eb 38e–38f 39e–39f
402–403 40e–40f 43e–43f 47a–47b 4ac–4af 4bc–4bf
4e5–4e7 5a2–5a3 61d–61f 657
```

snapshot复制须同时传播有效掩码；未知字节可以不解释地复制，不能升级为已知零。未模型化前驱写入还需使相应有效性失效，不能把构造值当当前完整配置。

本次0110自身足以建立operationMode=0：原接收表选1bf3fa，经1bf4d8→1bf4f2→1beef0 case0到1bef18，显式置r2=1调用1c5300；1c5310…16先经69adb6执行表项d16878:`10010000a39b6900`的699ba2。699ba6:`027a`读取请求byte8并零扩展，699bb4:`8266`写live+68。因此必须消费这笔实际10B配置写，再保存到17890fc，不能借用初始化0。

已观测的两次0118/22B另经d16b88→1c1128写+663:u8=3、+664:u32=1、+668/+66c/+670/+674/+678:u32=0、+67c:u32=1、+680/+298/+2a0:u32=0；它不写+68，不等同ADF/VDF缓存。新配置owner与队列helper正在实现，仍未启用0110正常回复。

## 回复域与模式任务完成分离

P-0110-2：699556(0110,result)→1c5b14映射event21a，1c605c…76生成type1/28B信封，result在+c。handler1c3874…38c4在byte+5未完成时调用69b89c，再置byte+5=1；result非零清byte+7。

69b8f6:`41f21010`写1110，69b918:`0596`原样写result，**没有ADF/VEF命名空间OR**：

```text
原成功：0d2010110c00018000000000
原拒绝：0d2010110c00018001000000
```

1c78e0按event19从每请求source FIFO取动态caller，经69b830→69e9f4 pop；565204独立分配12B，bec024设source92840747，564b38发送，失败565300释放临时回复。禁止10B请求复用为12B回复或固定本轮caller。

原回复事件可以先于模式任务完成排队。**两次event21a有不同作用**：第一次在state+5=0时发送唯一1110并置+5=1，成功时+7保持busy1；第二层work再生成一次completion，1c33f2…340a看到+5=1，置执行owner byte+4=1并清state+7，随后1c389a…38a2抑制再次从caller FIFO取值/回复。验收需分别记录first completion、unique1110、child执行、second completion和busy清除。

后端不能把“AP收到了raw0”写成模式子任务已完成；也不能为了等待全部任务而引入原序列不存在的循环依赖。真实入队/执行/资源消费/第二次完成必须单独验收。

## 新有限模型与前驱准入

16条BB前驱的本地配置/作业/回复路径均已检查，无10efa3c.word0 setter调用。0161 LUT分支另展开5项和16项TBB，215条可达指令/10个store均相对SP，所有可达调用限定为同步队列构造/清理、配置谓词、日志与VDF收发包装；`[1b60a0,1b631e)` SHA256为`bfe5c216e6a114d6c9dbf0fd7c37f8079678bfb98c088f4743b371e8946b3c06`。前驱raw证据文件SHA256为`467b1f5745e29a42a08364be96ea3b3a9ebdb797d24b9eda31f032d23f07cea0`。

新BBState是显式**虚拟source-image状态投影**，在guest constructor提前构造一次，按32B公开data初始化word0=1，沿已源审查的前驱保持不变；不是原CP live RAM读回，不从cp_cold mode3借值。其它未支持的模式请求/前驱使state knowledge失效并拒绝当前target选择。每笔不完整BB配置生产先使1760B语义掩码失效，当前0110的实际byte8写入后只依赖新产生的known4B operationMode，不把opaque复制升级为原CP实际配置。

权威代码为`runtime/analysis/device-models/`：

- `bb-mode-config.{c,h}`与`bb-mode-config-init.inc`：1565源已知/195未初始化字节、实际0118/0110写入、独立saved mode、1760B opaque数据及mask复制。prefix未知副作用会清语义known mask；known0的物理字节只是虚拟opaque载荷，不声称还原原CP内存。
- `bb-mode-work-queue.{c,h}`：generation1/target3一笔outer与inner，32B body/36B含长度记录，PMF adjustment0、4B未知gap不读取；queue3/task30、queue4允许task28/29/31，分别维护queued/in-flight/returned。
- `bb-set-mode-device.{c,h}`：精确10B准入、source-initialized同owner/前驱观察，要求原AP132d已释放与共同资源预约成功；实际wire更新opmode0、first21a、1760B复制、第二级work、second21a清busy、唯一12B raw0回复。回调/logger/release在私有锁外；发布前锁内重查fault，错误保留请求与清理指针。

当前有限本地调度策略同步串行运行两个work，queue4选择task31只是本地策略，**不声称原queue4独占task31或RTOS调度等价**。原首回复可先于任务完成；本虚拟profile保守延后其唯一AP回复发布至已证无需外部事件的target3/op0两级work返回，不推广到其它可能有依赖的分支。

## 原运行负例与0147待闭合项

- `run-76321phz`（72bb observer/263源）：原Common在132d之后进入exception monitor；新BB标签遗漏console镜像，不能从缺日志判断是否执行。已保全QCOW1/host树，guest cache未保存；普通SIGINT退出QEMU，geometry/X2 socket核验后GUI TERM/HUP、Xvfb TERM，进程/双锁全释放，无SIGKILL。
- `run-mv9041qv`（19383 observer/263源）：镜像修复后明确记录0147/680B为唯一`PREFIX_UNKNOWN`，state_word_known变0。初始化日志先于前驱可见；没有原AP1110成功消费。其partial QCOW1/host树和普通退出/双锁证据同样已保全，SD保存仍未验收。

此前`FULL_AUDIO_INPUT`只采样≤40B，遗漏了这一长包。0147 sender已定位eventae→1cebb0，将21×32B/672B平面表置独立缓冲，发VDF2001/030b。它不在124项BB共享配置writer表中，不写live config+68；不能因此替代设备消费证明。VDF主体1f5a38/1f5bd8实际打开/校验/提交/关闭handle，可能清表项+16/+17，不是空ACK；返回130b，经BB event2a2/ae产生1147，原内层E0外层应为00590000。

0147自身返回不走21a flag分支；通用尾部可能重放其它已排队模式请求，因此本地有限owner要求自身模式队列generation0/count0/inflight0、拒绝未支持模式输入，**不宣称原CP全局队列为空**。设备别名随后闭合到原201ad8构造：四个SID的数据root/dirty字节/672B表范围均不重叠BB模式字：

| SID | D | dirty=D+fa | table=[D+1680,D+1920) |
| --- | --- | --- | --- |
| 90590819 | 12468c8 | 12469c2 | [1247f48,12481e8) |
| 9059081a | 1238938 | 1238a32 | [1239fb8,123a258) |
| 9059081b | 123f8c8 | 123f9c2 | [1240f48,12411e8) |
| 9059081c | 124d860 | 124d95a | [124eee0,124f180) |

LCD/EVF/HDMI原服务构造入口已核，1c的实际实例未定位，不宣称其原启动成功。模型只按上述不可变地址合同校验其状态保持投影，不标VDF平面硬件应用完成。主会话独立核对8段原字节摘要与全部地址范围，证据为`bb-plane0147-state-static-pins.json`。增加680B0147正例、同尺寸未知0148拒绝反例后才重新准入；两轮旧失败不回填。

## 当前验证与剩余边界

配置helper19项pytest、双队列1038个C断言场景，以及新增22个真实0323→0336→032d前置后的BB组合/故障场景通过。补console镜像及680B前驱后主汇总379 passed/68 subtests、同步检查、strict C11/Werror与ASan/UBSan通过；原libc2.25下实际加载observer与constructor/API包装通过。

独立审查最初指出发布前未重查fault、外部回调持私有锁会重入死锁、早期owner日志不可见三项；已修复并以source回调注入并发prefix禁止send、release/guard/logger读取snapshot不死锁、constructor提前记录初始化snapshot覆盖。旧未通过状态不生成原AP成功收据。

本轮运行observer SHA256：`25eff6bd590d9ae4c87a5c5c2bfc97dbf4522a6b9d05962a142ce48f3469ec6a`，263冻结源；同轮归档SHA256：`d5fd6842667dadc5aeb0730fef882717da9e9ca06f3f3e2501fb7e3968b3a79f`。主会话核验归档内全部源码摘要，候选a0d/生产e235保持；以下原始摘录、行号、字段和严格断言结果均在本run的`bb-set-mode-native-evaluation.json`，console SHA256为`2d7f40152d009ed8eaeac11614242ae9091b755f5b3b599700ecbe8a7cdf12f1`。

| 本轮证据 | 限定结论/路径 |
| --- | --- |
| 构造早于86笔prefix，唯一0147/680B source alias contract1/local deferred0，无PREFIX_UNKNOWN | 虚拟同owner保持source初态word1；不是原CP RAM读回或全局空闲 |
| console12315实际10B0110；12319 first21a；12320 outer q3/task30/1760B data+mask readback | opmode由本wire写入并保存，不借构造0；data FNV=278b3b4a9203e99d、mask FNV=110b75312d7298c1，源/副本一致，known4/opaque1756 |
| outer出队read/write36/36、queued0但in-flight1、free10240；12321 second21a；12322双work returned | 两级真实本地work消费与busy收尾；队列空没有被误当成完成 |
| 12323独立12B1110 plainraw0；12324 requestfree0clean1；12325唯一reply指针free0fault0ap1 | 原AP消费元数据完成；释放日志没有单独PID/TID，收据明确`reply_free_thread_id_logged=false`，不捏造free TID |
| 12326同原Common382/PID259发48B请求到90050004 | 原AP确实从0110前进；新请求不是静态预测 |
| 两seq1444621684660817/1444622616565064，四阶段accepted→before→after rc0→reply stored1、pid259/tid344/drive65 | 原Fsys双flush/STOP/恢复、blocksync和cleancommit通过 |
| 两export与host全树3文件尺寸/SHA全等、owner112459与其组退出、无QEMU、双锁实际独占 | 本轮SD与收尾通过，无SIGKILL；旧失败仍false |

同轮初始Speech四帧/40B请求/epoch1/2强归属证明通过，两个foreign缓冲保持live，不释放/清零/重映射。host只有74B INPUT、9,670,656B database、406B mediapro.xml，无JPEG/MP4。主会话看原LCD HUD存在、中央仍黑；原GTK proof保持ok=false/automation_completed=true，不改完整相机验收。

下一实际请求为`0x90050004`的48B查询，raw `c461cf81a0a0a0a00100300018000000300000007f000000001000001800020000000000020000000100000000000000`。AP/CP内容合同正在独立调查，不假设无资源Get，也不借用不同registry owner。`bb_set_mode_native_verified=true`仅指本节控制与虚拟工作合同；EE仍0，`capture_verified=false`。

本实现不调用ClkCtrl、VSignal、模式位图003e、Input/Output/Monitor/AIP等未选中的复杂分支，不导入ADF event9当BB工作事件，也不强造AIP S1。原CP/硬件/图像帧与拍照录像仍未验收。

本轮两次EE快照均enable/source/status=1/0/0，Backup pending0，group0 current2f/stop0，queued31→40，JPEG request0。自然快门四阶段输入已提交，但没有新的Still入口或照片。最终目标仍为原固件JPEG/MP4写目录SD并可独立解码。
