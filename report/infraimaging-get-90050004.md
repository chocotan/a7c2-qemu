# InfraImaging 90050004：连接前的冷态 PinGet

`run-2r73dber`已消费三笔独立冷态Get回复：原AP PID258/Common381对 `(0,2,1)`、`(8,2,0)`、`(3,2,0)` 的56B消息均按同tid/sender/waiter、同lease/指针实际释放rc0。131项相关宿主回归、原libc2.25加载通过；同轮双原Fsysflush0/STOP恢复/host三文件全树SHA/cleancommit与退出双锁通过。见[本轮通过收据](infraimaging-get-native-proof.json)。随后13笔图连接请求均明确拒绝；本节只验收Get，`connection_verified=false`、`format_consumption_verified=false`、`capture_verified=false`。

## 实际等待及AP合同

前轮 `run-42_4pb06` 的原AP完成0110并释放唯一1110后，Common382/PID259在console12326发送：

```text
target=90050004 source=81cf61c4 bytes=48
c461cf81a0a0a0a00100300018000000300000007f000000001000001800020000000000020000000100000000000000
```

AP路径为 `get_infra_pin`（3511074）→`RecvAsync`（3510fa4）→`DataflowInfraReceiver::ReceiveASync`，外层48B、内层24B `{1000,0,24,2}`，键为三个完整u32 `(0,2,1)`。请求的外层`+20=7f`是opaque字段，不能要求零。

原用户栈给出的本次连接两个实参按 `{SID,type,direction,index}` 排列：

| 端 | 描述符 |
| --- | --- |
| source | `{90050004,0,2,1}` |
| sink | `{9284074a,0,1,1}` |

保存FP候选链：dataflow33c5c→appFw3510ff0→3511158→35113a4→35a9c98→35a9eb4→34dc514→339d998→33aaa3c。Still后、自然快门后两份顺序采样的syscall29/SP/PC前后相同，仍不称为原子采样或正式unwind。AP原字节/栈摘要在`next-90050004-AP-source-pins.json`。

AP期待独立56B外层/32B内层回复；`get_infra_pin`将内层`+18 owner/+8 type/+c dir/+10 index`重排成上述描述符。`connect_infra_pin`比较完整描述符，不相等会走abort分支；它随后还要查询第二端并发起连接。这个Get成功不证明整个Connect完成。

## CP源证据及冷态实例

仅依据公开ALLLANG 2.01的cpapp-b.bin，SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。本节地址为**CPVA，raw=CPVA−108000**。

| 项 | 原地址/内容 |
| --- | --- |
| 接收入口 | 46ee2c，46ee68..76以完整SID90050004接收；错误字符串InfraImaging.cpp |
| 构造器 | b09f06，独立Receiver=1a3a420、Sender=1a3a424；不是InfraBB构造器 |
| 六属性表/对象表 | 1109ee4 / 1109f44 |
| 槽1构造 | b09f7c..90：对象1a3a460、属性1109ef4、Sender1a3a424→68b582 |
| 公共Pin构造 | 68b582，实际写self+18..24、peer={ff,ff,0,0}、state+28=1，不依赖BSS零 |
| Get分派/查找 | 46eec4..eee6→46f04a，46f076..f0a4比较三个完整u32 |
| state getter | 68c3a4：原字节806a08607047，即读对象+28并存到输出 |
| 回复 | 46f2dc..f35a：读当前对象状态、owner/SID90050004、status0，独立Sender→68c67a |

| 槽 | `{type,dir,index,owner}` | 原对象token |
| --- | --- | --- |
| 0 | `{0,2,0,90050004}` | 1a3a428 |
| 1 | `{0,2,1,90050004}` | 1a3a460 |
| 2 | `{0,2,2,90050004}` | 1a3a498 |
| 3 | `{0,2,3,90050004}` | 1a3a4d0 |
| 4 | `{3,2,0,90050004}` | 1a3a508 |
| 5 | `{8,2,0,90050004}` | 1a3a540 |

主会话独立验证权威目录内同SHA原件、六属性/对象表、构造和getter字节；锚点摘要在`infraimaging-get-source-pins.json`。这里的state1是**端口未连接构造态**，不等同AIP的S1、BB状态、硬件ready或原CP活态。模型有独立owner，绝不借用sink InfraBB的21个端口/租约，也不在连接后继续强报冷态。

本虚拟Get回复的限定内容为：

| 外层偏移 | 内容 |
| --- | --- |
| +0 / OSAL source | 90050004 / 90050004 |
| +4/+8/+10/+12/+16 | a0a0a0a0 / 1 / 56 / 24 / 56 |
| +24/+26/+28/+30 | u16：1000 / 8000 / 32 / 2 |
| +32/+36/+40 | 三个完整请求键 |
| +44 / +48 / +52 | 读本实例state / 90050004 / status0 |

原拼包路径没有赋值外层`+20`，源值未知；共享传输将其置0只是**虚拟padding约定**，不能称为源证明的零，也不复制请求的7f。原CP接收包装会先复制并释放原消息；host adapter的请求释放顺序不宣称与原CP相同。

## 实现、检查和未完成连接

`infrabb-registry.c/h`复用该文件已有多个独立native owner的模式，新增`native_infraimaging_*`；底层Get/独立lease框架不改。`menu-observe.c`只在既有`MENU_PIN_REGISTRY`开启时增加source filter、dispatch/free和`FULL_INFRAIMAGING_` console镜像，默认无此变量时关闭。没有新增开关或把Connect并入Get。

`test_infraimaging_registry.py`包含原CP六属性/对象/getter字节断言，以及新旧两个owner的strict C11/Werror/ASan/UBSan运行。新C fixture核exact56B内容、两个动态caller、全部六键、完整u32拒绝、独立owner、未知reserved输入、64B Connect拒绝、错误释放保留租约。4项通过；连同BB0110/032d端点与profile，131项通过。测试不称为原AP成功。

sink侧源审计已证明这条边不能只置connected：原64B peer-connect将source描述符存入sink.peer、state置0并回复72B `8100`后，还要执行posthook。该sink后处理选择IN1，申请DMM **unit404/owner284** 的216B command20，验证实际handle/open/size，向真实映射backing写SSYN（header word06000000、key0、16B载荷`01000000000000008007000038040000`），command25关闭后向90050004发送80B `1000/0104/38/1` 格式通知。command25不是owner release；原peer回复的send返回被忽略，不能据0认定投递或后处理完成。

## 本轮实际原AP消费及连接负例

新observer `65f4a17704d571bda59dcc8873d63176f820c0177d54a46ba89c7a0c83099308`，264份冻结源。同轮归档`43b57206f66de0df932cd623c5b30a08c297bfbd108fca43a970fc4abc153329`，按run收据与归档内全部源码摘要核验；console SHA256为`5a656a9afaee3c20f1972e2c75662cc984edbad445f37315735728848f2b7a18`。

| 实际Get键 | 槽 | 原始消息/释放日志行 | 结果 |
| --- | --- | --- | --- |
| `(0,2,1)` | 1 | 12195..12204 | 48B查询→独立56B，lease1，同原waiter381释放rc0 |
| `(8,2,0)` | 5 | 12213..12216 | lease2，同原waiter381释放rc0 |
| `(3,2,0)` | 4 | 12226..12229 | lease3，同原waiter381释放rc0 |

三次reply均返回owner/SID90050004、当前冷态state1、status0。随后各对端Get也实际消费，原AP共发13笔64B图连接请求。第一笔是源`{0,2,1,90050004}`→sink`{0,1,1,9284074a}`，后续包含8型控制、ADF音频、BB→VEF、VEF→PinMem及显示相关边。每笔均有对应UNSUPPORTED，未报告连接成立或发布格式；AP错误路径继续执行不等于这些边成功。

所有尝试之后，原AP实际发出24B `302c`到90030001，raw `00002c302700008000000000000000000000000000000000`，仍被CP background记为未处理。原Common381此时在futex syscall98等待，EE仍1/0/0、group0 current2f queued31→40。当前应先恢复图的实际数据连接与格式生命周期，再验302c成像依赖，不据到达302c提升图成功。

严格评估在本run的`infraimaging-get-native-evaluation.json`；旧通用registry验收器要求旧harness的`summary.json`，本harness没有该文件，因此没有伪造summary或削弱旧判据。新评估独立核6构造、3对消息全文、原tid/sender/lease/free、13连接负例与本轮SD。公开收据不把GTK整体`ok=false`改成成功。

本轮Fsys两seq1448483410228497/1448484345744316，PID258/tid343/drive65四阶段均可见且flush0，STOP恢复、host三文件与两export尺寸/SHA全等、cleancommit22。owner143956及其组已退出、无系统QEMU、主锁/card锁实际独占获取释放，无SIGKILL。卡上只有78B INPUT、database与XML；无JPEG/MP4。

## 尚待真实连接和格式消费

该DMM buffer/格式生产与source侧实际消费/引用收尾尚未实现，不触碰现有Speech 405/406缓冲。下一项是实际第一条9005→InfraBB连接及其DMM404格式流。source调查已保留已知成果，未闭合字段继续拒绝，不泛化ACK其它13条边。EE、JPEG、MP4仍为零。
