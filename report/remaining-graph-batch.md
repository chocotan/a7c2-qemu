# 图连接的并行实现与验收边界

最新结果：`run-ouc1t64_` 已同时完成全部13条连接的原运行验收，HDMI11两条原内核UPM及24条原AP条件通知、OSD12持久SSOS数据、13份原AP回复及本轮SD/退出均通过。见[最终报告](all-graph-connections.md)和[13边收据](thirteen-edges-native-proof.json)。下面保留各连接合同与此前阶段；当前剩余前沿是`302c`成像启动，JPEG/MP4及capture仍为false。

本成果使用公开 ALLLANG CP 原件，SHA256 为 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。仅运行隔离的本机 QEMU、目录型虚拟 SD；不使用完整 dump、真机、物理 SD 或网络。

前十条加第十三条，共11条连接已通过 `run-sp_b6ivq` 原运行验收：c7d815 observer/302冻结输入，原AP258/TID381消费11份独立56B完成回复，均同sender、free0/fault0/ap1。1681项/139子测试、原libc2.25 ABI及本轮SD双flush/全树摘要/cleancommit/退出双锁通过；d847独立复核无P1–P3，详见[11边收据](eleven-edges-native-proof.json)。第七条原sender修复前的 `run-wv99y4lx` 保持拒验，不回填。

OSD12现已在独立新运行 `run-1xdwxzgj` 完整通过：16份e1700持久资源、48笔DMM、16次SSOS消费和原AP259/TID382唯一56B回复消费；同轮SD、退出双锁及完整选中镜像保留均通过。前十条加第十二、十三条共12条，见[12边收据](twelve-edges-native-proof.json)。首轮 `run-rhvtidg2` 因整份共享镜像后来被重建，保持未完整验收，不回填。

剩余HDMI11已直接实跑：CP参数表读错命名空间已根修，driver初始化及完成节点已消费；原内核UPM释放快于用户账本退休，现接入真实内核收据与专用数据邮箱，继续本机VM验收。**第11条、`302c`与拍摄仍未完成，`capture_verified=false`；EE0、JPEG/MP4零。**

## 连接矩阵

端点顺序为 `{type,dir,index,SID}`。

| 边 | Source → peer | 已闭合的内容 | 当前状态 |
|---|---|---|---|
| 7 | `{8,2,0,905a0048}` → `{8,1,0,90590818}` | 32B event8；VEF ordinal15；PinMem RawPinManager回调返回0；无新增格式/marker/DMM | 原运行通过；仅原sender释放才算AP消费 |
| 8 | `{0,2,1,90590818}` → `{0,1,4,91670464}` | PinMem真实12B event6与保存的64B原请求；Scalar IN4普通接收 | 原运行通过；精确canonical Get退役 |
| 9 | `{0,2,2,90590818}` → `{0,1,0,9058003f}` | 相同event6；ADF type5-only输入回调不选中；source YC回调因dir2不生产格式 | 原运行通过；前置ADF配置历史保持 |
| 10 | `{6,2,0,90590818}` → `{6,1,0,928d0783}` | 同一event6；DrawInfoRawManager选中方法仅返回0；复用既有DrawInfo registry | 原运行通过 |
| 11 | `{4,2,0,90590818}` → `{4,1,0,909a015a}` | 三个前缀输入、Initializing→HPD_Lo、4806/job6；2条原内核UPM＋24条原AP条件消费 | `run-ouc1t64_`同轮原运行通过，真实kernel收据退休、无二次free |
| 12 | `{1,3,0,90590818}` → `{1,3,0,9080003b}` | 精确3→3；独立e1700池16份持久资源、48笔DMM、16次0102双向消费 | `run-1xdwxzgj`原运行通过，owners/opens各2持久保持 |
| 13 | `{5,2,0,9058003f}` → `{5,1,0,909a015a}` | HDMI所有状态connected=true写同一共享byte+60=1、返回无后继 | 原运行通过；同owner写1/known1/writes1读回 |

13的true分支不依赖11或12成功，准入依赖实际第10条的同sender回复释放。随后`run-ouc1t64_`已完成全部13条的联合原运行验收；这些连接成功仍不代表成像或拍摄成功。

## 真实消息与事件消费

各连接均要求四份独立控制消息：64B `1000/0001/28/2`原请求、64B `0100/28/1` peer请求、72B `8100/30/1` peer回复、唯一56B `8001/20/2` AP完成。完整端点/SID和动态caller必须读回；source `1→2→0`、peer `1→0`，清pending和保存的caller。发送、原请求释放、AP回复释放分别留证，失败不抹历史。

7使用已有VEF16对象的slot15及PinMem13对象的slot12。源handler raw `5f99fe`清零32B参数，再存回复inner指针并提交event8；`10cb3e`恢复保存的原请求，比较完整peer后进入通用完成。native使用显式32位token绑定仍存活的独立回复，不截断64位宿主指针，也不声称原CP指针/RTOS调度相同。消费后再核VEF实际表ordinal15，原后处理只选1/2/3，因此本边无格式副作用。

8–10复用已有 `pin-peer-connection.inc`，没有另建端口或缓存。原PinMem context实际vptr是CPVA `d27660`（raw `c1f660`），与handler自身虚表不同。raw `5db222`构造context；`+8`读取保存原请求的S/P，`+28`读取原inner，`+30/+3c`读取/写入phase，`+80`登记wait6，`+84`读取本次event参数。raw `5d74ba`实际建立**12B参数**：回复inner指针和两个零字；`+78`调用factory `5dd814`，恢复原队列请求进入 `f882c` phase1，比较原P与回复P后才调用 `5839a6`。12B不能照抄VEF的32B。

新引擎保存原64B内容和caller，验证phase1/wait6、独立72B消息、参数token/回复inner绑定、完整peer/status/tail后消费event6。callbacks放在私有锁外；foreign PID先于锁拒绝；inline/跨线程free与send失败交错不得重复清理。独立消息所有权和DMM引用不是同一件事。

宿主组合fixture实际执行前置生产模型，读取并保持既有整块backing和快照；不以预填前驱snapshot替代已消费数据。

## 精确Get退役与共同资源门禁

累计Get次数不能证明**选中的那个键**已完成Get并由原sender释放。本批在共享registry根层补准确按键的退役证据：由真实Get lease携带对应canonical索引，只有正确destination、成功释放且同sender线程才记为完成。别的端口多查几次、高位别名、错owner、错线程、send失败或尚有live Get，均不能替代目标键的证据。既有Get wire和legacy入口保持。

原404池、Speech405/406外部资源、NoMem/AB失败S0及旧ordinal1历史必须保留。新7/8/9/10/13使用共同资源gate编号11/12/13/14/17；source为VEF或PinMem的自管dispatch置于legacy外锁前，未选中消息再落旧路径，避免双锁。资源准入条件不因增加边而放宽。

资源trace前缀统一按owner编号产生；同时修正原BB资源锁失败误标为ADF_PROC的前缀。它不改变资源准入或成功判据。

## HDMI两条边的不同边界

音频13的业务后处理并非纯NOP：它写现有HDMI配置owner的audio-connected字节。原singleton指针位置为CPVA `01791f04`，byte偏移`60`；旧值未知，新写1后必须读取同一owner的known/value/write次数。所有十个原state的true分支同效，不需要猜测current state；返回0是“无下一state”，不是协议status。分辨率、帧率和旧配置历史保持，不能据此声称PCM、HDMI输出或成像ready。

视频11的true分支不统一。原构造安装Initializing；若仍在该state，必须执行exit→HPD_Lo entry。entry包含两份16B消息，目标`80920572`，内容分别为 `{00920117,0,009a0000,0}` 和 `{00920117,2,009a0000,0}`，及诊断载荷/条件控制。原UPM consumer执行`k_psave_api`并释放同一消息，没有ACK，不能用空reply代替。

`run-4gqygshc`仅能证明8笔HDMI配置和4笔Get；其冻结observer没有镜像`HDMI_PHOTO_REQUEST`、`HDMI_PHOTO_SERVICE`、`PIN_HDMI_SERVICE`，而日志文件指向`/dev/null`。因此缺少这些日志不能证明没有0102/0109输入，不能反推RSEN_Lo或Initializing。

本批已补三类镜像，并按每笔HDMI/PinMem入口记录source、长度、序列和完整字节（上限4KiB；超限或来源/长度未知明确`complete=0`）。PinMem也记录，以审计type4 manager gate的f01f历史，禁止Connect时临时清0。实际C审计块的12项测试通过：两域字节重组、界限、未知来源/长度及default-off。这个观测补丁本身不设置任何HDMI状态。

## OSD必须完成的资源合同

12的 `3→3`由原方向表证明，共享connector已只为该精确PinMem/OSDPin键增加分支，保留其余2→1及全部冷态/peer/pending检查；两端复用原registry，不建影子owner。

独立unit `e1700`使用显式虚拟16×256B池，原allocator容量与原CP页表保持未验证。资源为四份peer key0/64B、四份反向key0消费产生的tag101/16B完成、四份source tag100/128B及四份tag102/32B。共16 allocate、16 share、16 open及16次80B通知；连接完成后全部保持owners=2/open_count=2，creator仍可写。初始化没有逐通知close/free，不借404池。

source SSOS版本字数值为`0x01000000`（小端原始字节`00000001`）；peer使用独立header数值1/flags3，不能混用。`100/101/102`是segment tag，**不是DMM unit**。

| 格式 | 已证明写入 | 必须保持unknown |
|---|---|---|
| tag100/128B | 0..3=1、8..9=0、12=0 | 其余121B |
| tag102/32B | 0..3=ffffffff、4..5=0、8..27=ff | 6..7、28..31 |

两方向SID分类均选80B `1000/0102/38/1`，不是0103。原路径`5d646c→5d6588`消费peer key0后生成四份tag101完成；OSD消费者`46aefc→46b0e8/46b2f4/46b5d4`登记101/100/102。初始tag101 mask0与tag100 inactive路径不调用plane/FIFO；source post只将选中的tag100 backing count改0，不重发通知/share/open，故OSD缓存count1与backing count0有意不同。

模型已实现实际映射读取、known mask和持久引用检查；unknown字节不当作零。metadata_ready不代表GPE、硬件或帧ready，Disconnect及active rows仍不支持。200B ulog是原best-effort诊断，不作为业务ready证据。原OSD Get收据不回填；OSD12的新原运行已完成上述数据/原AP/本轮SD及退出验收，不能提升为图像帧或拍摄通过。

## 本批复现与验收顺序

唯一运行源码为本目录的 `../runtime/analysis/`。公共入口使用新增三个default-off开关，继承前六条精确public ALLLANG链：

```text
A7C2_VEF_PINMEM_CONTROL_CONNECT=virtual-vef-control0-pinmem-control0-v1
A7C2_PINMEM_PEER_CONNECT=virtual-pinmem-scalar-adf-drawinfo-chain-v1
A7C2_ADF_HDMI_AUDIO_CONNECT=virtual-adf-audio0-hdmi-audio0-v1
A7C2_PINMEM_HDMI_VIDEO_CONNECT=virtual-pinmem-video0-hdmi-video0-initializing-v1
A7C2_PINMEM_OSD_CONNECT=virtual-pinmem-osd0-osdpin-if0-ssos-v1
```

最后两个开关各自要求完整peer chain，彼此及音频13不互相依赖。视频owner必须在HDMI任何输入之前从constructor建立Initializing历史；通知没有真实接收/同线程free证据时异步连接保持pending，不发送成功AP回复。

它们对应guest `MENU_*`变量及typed receipt字段。三端PinMem组合owner初始化必须全部成功，运行时仍逐边等待实际前驱AP释放。普通guest变量不能绕过host完整链；private/full seed、网络及冲突profile拒绝。

待所有生产写者稳定后，统一运行相关新旧测试、冻结逐文件源码摘要、原libc2.25 ABI加载，再用唯一VM/双锁做本批原AP验收。每个端点需要精确wire、事件参数/实际数据消费、marker或无副作用读回、最终所有权和原AP释放；同run重新验证SD双flush/全树摘要/cleancommit与退出锁。失败run原样保留，不借旧run的SD或AP结果。

最终JPEG/MP4验收仍要求原固件实际完成拍照/录像、写入虚拟SD并可独立解码。当前未达到该判据。
