# 0119：VDF面板翻转即时配置的有限模型

当前`run-dvpe50ts`的Pool0/324实际等待28B请求：
`0d2019011c0001800101000000000000000000000000000000000000`。
它发往共享BB端点92840747，但原功能是SendVDF_SetPanelReverse，与音频无关。
拍摄主界面仍未恢复。以下模型仅保存虚拟显示配置，不执行物理面板驱动，不宣称像素翻转。

## 原始依据

CP代码以下明确区分raw/CPVA，CPVA=raw+108000；appFw用ELF VA。

| Evidence | Finding | Path |
|---|---|---|
| appFw ELF34e9f48构造；34e9fcc→34e552c等待12B | 200d/0119/28/8001，当前h1/v1/osd0及timing0 | 按实际完整封套/字节域校验，不从worker名称猜接口 |
| CP rawbd3ea的119 table→bd7aa写内部25；bbff0 table→bc214→c4d2c | relay是SendVDF_SetPanelReverse | Kuna JSON与原Thumb立即数/字符串交叉核对 |
| rawc4d70..edc读u8+8/+9/+a；+c是timing，+10仅timing1使用 | hrev/vrev/osdRev为三个独立字段，timing为另一域 | 当前仅支持bool H/V、OSD0、timing0、其余零的观察子集 |
| rawc4fda..fea发9059000e、source928407b9、20B 2001/0101 | 需VDF配置consumer，不是返回空ACK | 模型构造对应internal配置，独立保存反转属性 |
| CPVA6c90ba识别2001/0101；6c90e8包装2001/f02e | 原display→device步骤 | 模型明确仅做virtual即时配置，未模拟原device调度/时序事件 |
| RTTI VdfDisplayCmdSetPanelReverse/DevPanelCmdSetPanelReverse及vtable | CPVA6db824为device执行分支 | 类型身份从原RTTI/表核查，不靠邻近函数猜测 |
| CPVA6db93a→Accessor+444→raw5dbfc4复制16B，其中已定义前三u32为{0,h,v}；+44c存OSD属性 | 真实配置有持久状态，第四word未证明原始定义 | snapshot独立reverse_properties/reverse_osd读回，virtual第四word显式0 |
| rawf69d4的PanelEvfInfraRvsCall将H/V映射为0/1/2/3，发027d0728 | 控制byte=2*h+v | 显式virtual配置consumer保存control并读回；hardware_driver_executed0 |
| rawbf674比较590000并去域成0，bf69c构造1119/12/8001 | 此命令raw成功为裸0，不同于0165 | 严格检查12B回复0，不套590000状态 |

`audio-0119-static/relay-kuna.json`保存指定relay的Kuna输出（目录名保留最初日志分类，
实际owner已纠正）。CP原SHA与其它报告相同；appFw同已验证原件。
主会话直接核过原参数、send目的/长度、RTTI槽、属性setter和控制byte映射。

## 模型范围

新增`MENU_PANEL_REVERSE=virtual`默认关闭，要求observe且不共用实验send-GOT。
只在显式虚拟配置owner里执行：

1. 接收合法28B/即时mode0/AP动态源，拒绝原特殊源81b40549的另一套字段语义。
2. 构造20B VDF internal配置，consumer读其H/V字段，写独立属性{0,h,v,0}和OSD0。
3. virtual control byte保存`2*h+v`，读回同一状态，记录已消费次数。
4. 独立分配12B回复，经原消息传输投递；原请求/回复各按实际owner释放、lease跟踪。

这项成功只表示虚拟配置被消费。原设备的VFC时序、排队/取消、panel on状态、输入buffer、
物理027d0728及其它原分支未完成，不以缓存成功宣称硬件原成功路径等价。
`pixels_flipped=0`始终显式记录，没有frame数据被翻转。非零OSD、非零timing、非bool值和
未观察的保留字段一律拒绝，不悄悄扩展为原所有输入均等价。

host测试覆盖4种H/V组合与control读回、默认关、错误参数/封套、裸0回复、原waiter释放、
发送失败时状态回滚。当前Sanitizer和动态实验已启动，结果另行验收。

后续device Kuna4函数均无function error，确认原即时设置还依赖VFC计数、device phase和条件buffer更新，
不是同步直写缓存后立即完成的完整原路径。本模型明确没有模拟这些原时序和buffer生命周期，
仅验收virtual面板配置consumer；不能据其返回0宣称原设备翻转调度已恢复。
独立核查还纠正了属性记录的第四word：原setter复制16B，但当前只证明前三项有显式写入，
不能将模型使用的尾word0写成原代码必为0。控制byte只消费H/V两字段。

## 动态配置结果

`run-f6pnqj0o`原Pool0/324发出观察到的0119，虚拟owner写properties=0,1,1,0、
H/V=1/1、OSD0，control3读回3、consumed1。独立12B裸0回复pointer=`0x7f8297ec00`、lease3，
原waiter324复制/释放rc0；随后该worker回到空闲`34b9528`。
console SHA256=`b0bb2e9bd7ad814cead832bb0a910ce1d303c1c7594e2f30cdb75f9f05362400`。
属性/control/scope/status/free五种破坏负例正在执行，尚未领取结果。

后续该验收已通过：2测试含5种破坏负例，裸0回复与误tag590000区分、原waiter释放及virtual scope均通过。
正式`panel-reverse-native-proof.json`明确physical driver、原device phase、VFC调度、像素翻转均未验证。

Common328仍在3552ea4查询unit容量，不再有0119 worker等待；原UI future未结束。
日志明确hardware_driver_executed0/pixels_flipped0，不能由配置通过推定像素已变换。
