# 409d / 4072 / 3003 / 3012 控制与数据边界

本批复用同一个默认关闭开关：host `A7C2_CP_CAPTURE_FORMAT=diagnostic-cp-ee-controls-v1`，guest `MENU_CP_CAPTURE_FORMAT` 必须精确同值，且前驱诊断302c、有限4073模式0和全部13条连接均满足原有条件。构造器先初始化402d和startup控制owner，再初始化EE控制owner；没有启用模式1快照或3003数据回复。

## 已核的线上合同

公开CP原件 `runtime/analysis/menu-root/cp/cpapp-b.bin`，18,090,880 B，SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`；CP地址仅文件映射范围使用VA=raw+108000。公开appFw SHA-256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。以下地址为各自原件VA，不混用两者偏移。

所有请求OSAL source=80020002、destination=90030001。正文u32(+4)是opaque cookie C，回复必须原样回显；它不是OSAL source。12 B控制回复是type1、保留byte1、原opcode、C、status=f000；409d/3012的原构造未给byte1赋值，本虚拟诊断传输明确选0，不把它称作原固件保证。

| 命令 | AP与CP源点 | 请求→回复 | 范围 |
|---|---|---|---|
| 409d | AP35457ec/3545950/3545974；CP参数表10fb6cc、handler35836c、发布callback358420 | type5/12 B→type1/12 B | 四个payload byte分别存165a8f0/f4/f8/fc；诊断只审计和读回四字段，不宣称原crank已应用或发布 |
| 4072 | AP354565c/35456ec..354570c；CP参数表10fb370、handler357094 | type5/12 B→无回复 | CP读byte8/9并存165aa68/9；AP不登记等待。虚拟owner消费两字段，原request释放成功后才记oneway_consumed；绝不分配/发送ACK |
| 3003 | AP3546040/35460a8；CP4b6064转event2，producerb224ae | type0/24 B→type1/16 B | 尾四字节是状态数据，来源如下；本批不处理 |
| 3012 | AP3546244→35460e4/3546284；CP4b6064转event8100，producerb225ee | type0/24 B→type1/12 B | 原固定destination80020002/source90030001；仅预先实现诊断传输，实际未到达时不记消费 |

3003的16 B回复不能简化为12 B，也不能给最后四字节填零成功：

```text
P = u32[b2ddb4() + 34]
reply[12] = u8[P+46]
reply[13] = u8[P+47]
reply[14] = u8[P+48]
reply[15] = u8[a499f4()+8]
```

AP通用接收器35358b8复制16 B，3003局部caller只检查reply+8是否f000；35314fc→36825e4→3682538还会记录尾部数据。因此“不参与这一局部业务判断”不等于padding或从未被消费。其四字段业务含义和虚拟状态来源须另行闭合。

## 所有权、前驱和线程

实现位于 `runtime/analysis/device-models/cp-ee-controls-diagnostic.{c,h}`。两个回复lease与一个单向消费槽按409d→4072→3012执行，一条一次，transport失败保持sticky fault/retained指针。3003和不支持的命令返回未处理，不取所有权、不造回复。

父guard先预约共享资源，再验证同一PID内302c/4073/402d/4014/4057的原request/reply释放成功，以及旧13连接实际完成和持久OSD引用。条件40c8没发出时不要求它的虚构收据；一旦发出就必须完整完成。每一对回复仍要求该对原sender=waiter、原source/长度/字节读回相符。

真实 `run-ktnudlyz` 的前驱sender为382，后继409d来自worker379。新后继guard按已完成前驱cohort校验，允许当前worker不同；旧阶段仍要求当前线程与其前驱一致。没有把sender/waiter校验删除，也没有借其它PID或旧run状态。

## 验证和主张范围

联合自测首轮78通过/1旧声明集合失败，补齐两个新增false能力断言后79项通过；后续补真实leaf runner导入检查，同批80项、完整2490项/304子测试/360冻结源和原ABI通过。启动前leaf语法失败未产生VM，证据另行保全。EE owner另有132个C ASan/UBSan场景，覆盖单向不ACK、3003不处理、重复/乱序、source/type/长度、分配/释放/发送错误、inline及异线程free、fork与重入。以上属于本机组件测试。

同一批还纳入真实[虚拟光学→JPEG内存集成](../virtual-imaging-jpeg/README.md)：原RGB888缓冲直接交已完成引擎，独立解码检查光圈亮度、近远对焦清晰度、奇数尺寸/padded stride和边界，4项通过；不是guest帧或固件照片。

Evidence E-control-current最初为 `run-ktnudlyz` 的原409d包及保存栈，Finding F-parallel是后继实际来自并行worker；后续 `run-a547uk6q` 已实际由原AP258/TID378释放409d的12 B诊断回复，前驱TID381保持自己sender/waiter配对。实际下一等待是4000，修正了只列409d→4072的静态候选。新增精确movie profile后，`run-nzx01uc3` 又实际验证4000原APfree与4072单向原requestfree/无ACK，到3003数据等待；旧EE profile自身不扩大4000白名单。

Path P-control为原AP请求→精确诊断owner→独立回复lease或单向消费→原请求/回复释放→下一控制。原运行结果以各自新run收据为准，不能将host测试提升为原AP消费。业务应用、CP状态/快照发布、generation、原硬件、EE、frame、capture均保持未验证；`capture_verified=false`。
