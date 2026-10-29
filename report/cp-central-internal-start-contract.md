# 中央内部START：生产者与真实消费者

当前仍没有证据证明在本次AP302c前发生了自主3000/3003启动。新调查已缩小缺口：需要第一份实际接受的ADJ_MAIN adjustment记录，或独立生产的native mode envelope。CamMain构造器本身不排队这些事件。主会话独立核验[20个窗口](cp-central-internal-start-source-pins.json)；本文不执行原件，不改变生产代码，302c/capture=false。

## ADJ_MAIN回调不是自动启动

b23396是ADJ_MAIN adjustment interface的一条record callback，不因为邻近Release RTTI就称其为Release实例方法。原字符串fc6cb7是`Senser/cam_main_adjust_cmd_if.cpp`，dispatcher为4b7730；fc6b37为Init_ADJ_MAIN。初始化4b6ea8或4b6f76调用b22de0，b22de8..b22e04以endpoint900301d7、descriptor输出1a53274、Thumb callback4b7731、argument0注册同步服务。

4b7730按record+24的u16选择table，再按1b1e02e选择normal/alternate，查record+26的u16，4b7ab0通过BLX r5调用选中callback并传record。原件中有300个b23397字面指针位于e77f78..e79467，确定了间接调用来源，不确定记录的生产时点。

| block | normal / alternate root | event0 |
|---|---|---|
| 默认，包括0404 | e77f78 / e78658 | b23396 / b24002 |
| 0480 | e78f38 / e78fd0 | 两表均无event0，使用default b23c28 |

0480/event0落到default时写响应`08 88`并清响应长度。因此即使739a2a内部谓词允许0480/0，也不能说该组合经b23396 dispatcher可达。

已知内部selector739a2a只有在input+26=0、pending byte1acbf74=1、block为0480或0404时才选择start。它清pending，检查saved17922b8等于8则3000，否则3003。另一路先pending1，再从b1f2b0读取中间字段1a52ae0保存；这不是global current的快照。

具体反例：block0404/event0，但pending读取为0，即使saved word为8，也走739b42→739b6a→b230ca(afff)，不生产START。pending和saved值不能靠清零后的默认分支补造。

另有4d7d0c→739bba：1a9e872的u16与1a532a5的byte不等时，写128aaf0+26再调用739a2a；128aaf0不在原件文件映射范围，不能读成已初始化0404记录。b2407a还受1b1e031==0约束。需要记录原始输入和前序操作，不把callback存在当调用已发生。

## 已闭合的native mode消费者

ExecModeHandler由RTTI ce9d40确认，vtable槽e77b10指向Thumb4b4061。aggregate为1a52b38，handler位于+ac=1a52be4，CamMain位于+108=1a52c40，其+28/+30是独立member。

4b6698在900302d9接收20B envelope（十六进制20，即32B），4b66f4调用4b3e90(aggregate,envelope)。envelope首u32选择handler，虚函数接收envelope+4。handler0的record是：+0 handler0、+4 mode event、+8 cookie、+c origin/tag、+10..1f arguments。

ExecModeHandler::perform(4b4060)在guard前处理：event0经4b408c/4092调用b21f04(CamMain,8)写self+28；event2经4b407c/4092写self+28=2。这都不写global current。

event0检查b21fbc，谓词不为1才经4b475c→b218bc→b21702(command3000)→4b6958 guard；guard0才由b21718调用4b28d8(3000,1)。event2对应b21fb4、4b4780→b21898→b21702(3003)及同一guard。完整module/path/boundary提交仍需后续消费。

## 已找到的特定producer仍依赖外部请求

90030001 receiver4b3a7c接受type0/2，4b3b1a调用4b6064(request,origin)。request command3000在4b60f6转换为event0，3003在4b6118转换为event2，4b632c..6342构造上述32B envelope发900302d9，保留原request+4为cookie。

这是一个确实存在的producer，但它要求本轮缺少的AP3000/3003前缀，不能重新命名为隐式开机事件。b21604只构造字段并返回，不enqueue。

## 另一直接START：3005属于拍摄转换

后续[NEXT/IRQ源合同](cp-central-next-state/README.md)已核 `47550e→4b28d8(3005,0)` 的真正生产者 `4750e8`。它由排队callback内 `b0dc68` 调用，并先在 `4751f0` 查询3005是否准入；原320表的四项CURRENT为4e/8/4f/9，path分别为38→4e、38→8、38→4e、38→9，均翻译为3021。按该表绑定、busy0/CURRENT0时具体生产者会在START前拒绝，不能把它当自主开机起态来源。

拒绝仍有原副作用：busy镜像写入，以及 `b20a4a(seq,0,1)` 向900302d9发送handler0/event8200，独立byte1a5347a为0时另发0203；随后有原清理调用。callback是否在首个AP请求前执行、下游通知和其它writer历史仍未知，不将其压成无操作。

## 配置member与剩余边

4b6744调用510728从CP primary读key000300a8的4B到CamMain+30。主会话已用既有公开seed/BK4验证器独立读出该CP键为`06 00 00 00`，AP表不存在；这是配置member=6，**不是**global current=6。其真正用途由下一独立源边继续追踪，不能按数值相同建立状态。

剩余输入或顺序：ADJ_MAIN900301d7第一份被接受的150B record、建立pending1的前序event及saved1a52ae0来源；或900302d9中handler0/event0或2的原自主producer；以及guard所读post-constructor current/pending的来源。首次源码clear0已闭合，不代表其后没有变化，也不授权向外部注入3000或写current6/8。

这些消费者可用于有限模型识别实际已生产的事件；在真实producer缺失时必须保留unknown/pending。图连接、参数暂存、服务缓存和队列callback都不代替这一中央历史。
