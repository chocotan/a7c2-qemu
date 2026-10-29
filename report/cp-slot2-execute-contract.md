# 模块2业务执行与正常完成字

首个有限参数暂存操作与0323/032c的正常临时字规则已静态闭合，完整`8c736a`执行器仍未闭合。主会话已独立核验[20个新窗口](cp-slot2-execute-source-pins.json)，共2614B，及原CP whole-file SHA。本文均为CPVA；只有文件映射地址可减108000求raw，RAM不能如此取文件切片。`native_module_completed=false`、`302c_native_verified=false`、`capture_verified=false`。

## 实际执行顺序

`8c736a`是多个消费者的编排，不是一个简单command switch。`8c7438..7544`先调用32870c复制旧buffer、暂存完整请求和输入并执行16B服务事务；8c8af0选独立业务对象及enter/exit回调；3086e0消费N+60对象及其+a0；8c8b44调用选中对象+0c；32f5e0从实际工作对象和资源构建输出bank。资源操作b0a608(80)/b0a610(80)使用resource2b及ffffff7f/80掩码，不能删成空ACK。

后续还有按原条件调用的8cb0c6、8774xx/8775xx、8c36aa；87f54a、311af4、30fa30、诊断及尾调88372e(C+f48)也必须保留各自消费门槛。队列不能绕过这些工作直接flip selector或发布完成。

## 可实施的第一业务操作

`8a3bd8(N,C,A,T178)`的有限主体已闭合。C=`2012a58`、A=`186bf24`、T178=`1656d98`，R=`le32(N+0)`，mode_b是b08868读取的实际byte[1b1dea5]。调用者32880e..328822先保存A+32d旧byte，再清0。

| 精确目标写入 | 实际输入 |
|---|---|
| C+f38 u8 | u32[R+92c]==1 |
| C+f39 u8 | u32[R+158]==0 |
| A+3ac u32 | R+3e8 u32 |
| A+3b0 u16 | R+3ec u16 |
| A+3b4 u32 | R+3f0 u32 |
| A+3b8 u32 | R+400 u32 |
| A+3bc u32 | R+3f4 u32 |
| A+3c0 u16 | R+3f8 u16 |
| A+3c4 u32 | R+3fc u32 |
| A+3c8 u32 | 同一R+400值 |
| C+798 u32，mode_b==0 | T178+2 byte等于1则写0，否则读R+1c4 u32 |
| C+798，mode_b!=0 | 原byte及known mask保留 |

所需最小extent：R>=930、C>=f3a、A>=3cc、T178>=3。仅被实际读取的值必须known；其余opaque字节不被填零。参数暂存不创建queue、timer、semaphore、完成callback或模块完成字。

此前32870c会从2018df8复制1350B到C、从1656f10复制178B到T178，并按旧状态/dirty/override执行其它恢复；这些实际buffer不能用全零代替。第一操作的实现必须接收真实已准备的借用buffer及mode值，返回“输入已暂存”，不能返回“命令已完成”。

## 完整u16命令与业务对象

328792..32879c读取`le16(le32(N+0)+6)`，写C+0和C+4；对应byte为2303、2c03、0203。1ad41f1/1ad41f2的独立runtime override可能将processed command替换为0300|override，不得忽略。

8c8af0调用当前业务对象+14 decoder，另有1ad4327 byte可覆盖object index。对象改变时原exit/enter必须按条件执行，再存指针10f9e3c。只对默认对象decoder350c88，0323与032c选index1/callback8c87f4，0302选index3/callback8c8ff0；这些静态映射不证明当前active object。

index1回调还看C+820：0走8c9792，1走8c96e2，2走更多字段依赖工作；322cf4等消费者仍未闭合。不能猜C+820=0。

## 首个真实服务事务

328c4a..4e给出地址handle92a20845。328d18..328d8e调用565204分配16B，bec024将metadata source设为90030001；初始body为：

```text
62019200000000000000000000000000
```

随后bec01c(handle,payload)分派，返回0才复制四个响应word到C+de0/de4/de8/dec。565300在分派成功或失败时均释放该分配。分配失败则不发生事务；分派失败保留原四字段并释放消息。90030001在这里是metadata，真正目的handle是92a20845。

服务的真实路由/消费者和四字响应尚未闭合，不能用虚构0响应代替。unsupported后端也不能被悄悄当成已经调用原服务并返回失败。

## Published bank不能回显请求字

32f5e0的两个直接producer为：bank+4从2013da8+0读取u32，bank+0从2013da8+6e读取u16。若C+4bc==1，330902又将C+1152写到bank+0，33090e将C+1154写bank+16。其余字段还有真实工作值和复制跨度。

这证明bank首字不应直接写为requested command；完整bank producer及其callee尚未全部闭合。

## 正常完成视图的独立计算

正常输出caller4dd09e..4dd0d2将P+2950传入8c9856→8c985a→8c76ec。路径为32b840→8c8b9c(input snapshot,previous temporary)→34ff4c(input,temporary,working state)→8c8eea(temporary,working state,P+2950)。8c8f30的`strh.w ip,[r2]`写的是计算后的临时u16，不是从published slot2 bank的offset0加载。

0323/032c的有限分支：input.u16[0]=working_state.u16[0]，input.u8[3]=working_state.u8[10aa]；temporary.u16[0]先来自working_state.u16[6]。status byte精确等于1才将temporary改为命令，否则保留prior word。两条命令都经TBH3500ec到3509e0。实现可计算这个临时候选值，但在其它消费者完成前不能把它当最终module observed。

status有具体producer：32b858调用a76188，32b884读返回对象H+2，32b886写working_state+10aa。H以1717510为base，受`**(u32**)19f9250==2`及bank selector1b1a0a3影响；具体stride须按原指令解释，不以未标进制的文字推断。H+2的生产、当前selector和freshness尚未闭合；不允许强置1。

0302在主TBH前还按working_state+129c选择0/1/2/3/4/other六条路径，不能把34ffd0的一个表项当全命令。3509e4..350a46的diagnostic force路径不是正常消费证据；8a6d8a进入刷新working-state的复制也有独立调用条件与时效门槛。

## 继续实施的范围

模块2队列已独立实现并通过宿主测试，见[当前实施矩阵](cp302c-implementation-status.md)。下一代码只实现本报告已闭合的参数暂存和0323/032c临时字计算；完整executor仍需：真实业务对象/override/C+820、92a20845服务响应、完整bank构造和必需尾部、status H+2的真实producer及正常view刷新。

即便这些数据相等，中央起态和phase观察器仍是独立门槛。本报告不发送302c/f000，不声明帧、JPEG/MP4或原CP执行。

## 当前模型验证

当前 `cp-slot2-inputs` 与 `cp-slot2-work` 宿主测试通过 **48 passed**；测试包含严格 C11、ASan/UBSan、未知 mask/容量尾部别名、借用视图、队列失败、fork、重入、0323/032c temporary-word 正反例。独立 review 提出的三个 mask `known_size` capacity-tail alias 反例在当前源码下均返回 `-EINVAL`，原 buffer 和 saved marker 保持不变；该 P3 已关闭。测试只证明输入暂存、队列所有权和有限临时字计算；没有 `8c736a` business executor、`92a20845`真实响应、published bank、normal G+10 refresh、module completion 或 native CP 消费证据。
