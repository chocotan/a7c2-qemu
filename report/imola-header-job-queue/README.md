# SPS当前输入Q：48指针环与8407路由缺口

已找到header管理上下文F+c的writer，以及Q所读槽的实际入队来源。Q是当前环槽保存的消息payload+10指针原值，不是一个未解释内存handle holder。仍未把发送方所选recipient接到这个具体F队列，也未证明实际header选择，因此Q=B/T及P/B像素尺寸单位继续未闭合。

本次公开Imola2只读静态核对，8个RAM0窗口1852B与完整原件身份见[source-pins.json](source-pins.json)。未执行固件/VM/网络/硬件，不修改此前3249/381冻结源；本报告是之后的独立补充，不回填该轮。

## 对先前SPS边界的澄清

[先前SPS网格报告](../imola-avc-sps-grid/README.md)的105268/160B pin范围和摘要正确，但**80105268是上一函数assert尾部，不是构造入口**。安装8024072c的入口是80105288，另有801052c8变体。window起点与function入口需区分。

80105c68的F来自第二参数a1，是frame/header管理上下文，不是header controller的this=a0。实际读取为：

```text
80105c88 L=u32[F+c]
80105c98 A=u32[L+c4]
80105c9c Q=u32[A]
```

Q自身的SPS bit-syntax语义不受这项参数域澄清影响；跨到P/B的alias仍需独立证明。

## 正向ring初始化与入队

8007d2fc分配d8字节，返回CPU对象L，初始化write ptr L+c0=L、read ptr L+c4=L、count L+c8=0、L+cc=0。8007d36c调用801c5938，延迟槽给a0=F+c，helper首store为`sw a1,0(a0)`，因此确实保存u32[F+c]=L。环容纳48个u32 pointer。

8007f974验证body18h字节，R=u32[message+18]=u32[payload+10]。8007faac..fab4把保存的R原值写current write slot；8007fae4..faf4取J=u32[F+20bc]并调用J.vtable+c(J,**同一个F**)。queued处理8007fb14通过801c5c7c执行同型`*slot=*argument`。80069c90是返回第二参数的placement-new，原字节0800e0032110a000，不做地址转换。

由此闭合的是message pointer→ring slot→SPS input Q，而不是地址值相等的推断。

## 发送侧同descriptor仍缺transport对接

在80083404第二参数D中，X=u32[D+10]被用于处理X+b44、X+1340等命令区，后续8008174c(this,**同一个D**)发送8407；serializer801c61b4保留body+10。发送recipient来自u16[u32[this+11d8]+8]。

这个X→发送body+10已证，但没有把该选定recipient和8007f974/8007fb14的具体F实例正向连接。另一个80174be4 MBP scheduler路线也用8407；不能因opcode与偏移相同就合并两条路线。也未找到独立的Q14/Q18←B/T14/18字段copy，以及后续所有阶段保持这两word不变的完整依据。

## Header选择仍是条件事实

8007f748有一个codec分支分配1644并调用801090c8，保存到F+20bc。该构造调用801044f4并安装派生vptr80240700，其+c=80109288；它从同一F+c→L+c4→Q取值，普通AVC分支到801094d8，再把Q交继承的embedded SPS writer。工厂条件是静态证据，实际配置选择未观察。不能将名义基类8024072c/80105c68直接当作已经观察的当前路径。

E1（ring allocation/store）→F1（F+c来源）；E2（入队原指针与same-F调用）→F2（Q来源）；E3（同D发8407）→F3（还差具体recipient/instance join）。下一步仅核这条具体route或证明geometry word copy，不重做已闭合SPS/UE算法。`Q_equals_B_or_T_verified=false`、`P_B_actual_pixel_dimensions_units_closed=false`，不新增猜测geometry code，`capture_verified=false`。
