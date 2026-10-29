# Digital Level：selector3通知订阅的有限模型

当前自然boot等在SID912f0335，原24B请求为selector3+20B零。
这是启用角度通知，不是请求一个已校准的角度样本。拍摄主界面仍未恢复。
本模型只提供显式虚拟通知控制；无真实加速度数据、无角度/错误事件、无原CP任务运行证明。

## 原始契约

以下CP地址为CPVA，raw=CPVA−108000；appFw地址明确为ELF VA。
原CP和appFw摘要与同目录前述报告一致。Kuna定点调查后对关键Thumb分支交叉核对。

| Evidence | Finding | 实现或验证路径 |
|---|---|---|
| CPVA58ec64注册、58ef98消费者，名称DIG_LEVEL_INFRA | 原owner在CP、SID912f0335 | 本地独立服务，不冒充原线程已启动 |
| CPVA58f112检查mode2、58f118检查started byte | mode!=2返回2；mode2/start0原分支返回0但没有动作 | 模型mode2/inline worker由显式virtual配置拥有，不从请求推导原状态 |
| CPVA58f126..132从selector3构造20B下游命令到90a3035b | 原0只证明投递接受，不证明有效样本 | 本地20B控制consumer保存enabled/countdown状态后才返回完成 |
| CPVA145d46..52预置enabled1/count30并按selector表派发 | 重复3重置通知计数30 | 实际保存持久开关及计数，无样本不产生通知机会，不自动递减 |
| CPVA58f086将结果写request+10，然后复制24B回复 | 状态是回复u32+10，其余沿用请求 | 保留原selector/封套，实际独立回复allocation，源912f0335→原动态AP source |
| 原worker取样58f354经90a30281，校准后才形成通知 | 订阅与有效角度独立 | 当前sample_valid0，不发18000001角度/错误消息 |
| appFw ELF34efa0c读frame+40=request+10，而reply在frame+48 | AP正常返回0可能是读取旧零，不证明CP成功 | 不用AP返回值作判据，要求模型consumer状态及同waiter回复释放证据 |

主会话独立复核CPVA58f100..150、58f086..0a2及145d3c..52原字节。
原模式来自backup键012f0003及其它启动条件；本模型没有修改或声称读取该原CP状态。

## 当前有限实现

默认关闭的`MENU_DIG_LEVEL=virtual`显式选择virtual通知服务，要求observe且不得共用实验send-GOT。
配置声明mode2、inline虚拟控制worker（实际执行在AP发送线程），不声明原CP主线程或硬件已就绪。
仅支持本次实际观察的24B selector3/其余零，selector4及其它输入明确拒绝。

服务将请求投影为20B命令，独立consumer解码并保存notification_enabled1、countdown30。
状态持久于进程；sample_valid0、latched_error0属于此虚拟owner，不能外推为相机实际传感器状态。
没有有效样本时不伪造角度值、有效标志、错误或事件；也不声称校准已完成。
回复发送失败时，已消费的订阅保留，原请求仍由调用者持有；这与异步控制已消费但回包失败区分开。
lease跟踪原AP动态replySID、原sender线程和原free结果，Get/音频等其它服务不共享状态。

## 验证边界

host测试覆盖默认关、合法订阅和重复订阅、错误selector/保留字节/长度/source、
allocation失败不改变消费数、reply-send失败保留订阅并释放独立回复、成功后的原waiter释放。
样本/事件字段必须保持0。实际动态消费仍需新run的REQUEST、CONTROL_CONSUMED、REPLY、COMMIT和FREE。
仅transport返回0或appFw继续执行不够证明模型或传感器成功。

当前正在运行ASan/UBSan、开关校验及QEMU动态实验，结果未预判。

## 动态消费

`run-dvpe50ts`已完成：Common328原24B selector3请求由virtual模式实际解码消费，
CONTROL_CONSUMED记录enabled1/countdown30、mode2、inline-virtual worker、无样本/无事件。
独立回复pointer=`0x7fb0514ec0`、lease1投递81cf61c5，原sender328 free0；request free0。
console SHA256=`da11297fc08b9914545cb265d684e193eeb16ee839aec0c3ce413ec711ccb175`。
host ASan/UBSan通过，observer开关9测试通过，旧成功JSON覆盖回归2测试通过。
订阅逐字段及5种篡改回归正在执行，尚未领取结果。

该验收后续已通过：2测试含5种篡改负例，且验证失败覆盖旧success的CLI行为均通过。
正式`digital-level-native-proof.json`保持sensor_ready_verified=false、sample_valid=false、angle_events0，
mode_source明确为explicit-virtual-profile。相同run的真实sound、032a路由及VEF-PinMem控制格式复核亦通过。

Common下一栈为`3552ea4←34d3794←305e780←305e9e8`，同时Pool0/324发出
BB端点的0119（实际为VDF SetPanelReverse，不能因日志族AUDIO就认作音频命令）。
这两处等待分别调查。UI仍等boot future；StillCa330 initial_arrived0，slot states0。
5张实际RGBA图均透明黑，不能由订阅成功外推为传感器、OSD或拍摄主界面就绪。
