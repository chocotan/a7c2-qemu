# Proxy/header实际路由：8407与8421必须分开

已闭合具体endpoint配置：8008174c的8407去conditioner1b；紧接着发送、携带同一D的8421才进入header manager19。由此取得CONDITIONAL_AVC_HEADER关系，尚未观察或解释opaque worker selector，不能无条件推广Q=B/T或P/B像素尺寸。

本次只读公开Imola2，8个RAM0窗口6812B及完整原件身份见[source-pins.json](source-pins.json)。没有改旧source或运行固件/VM/网络/硬件。本报告在3249/381冻结轮之后，独立补充[header job queue](../imola-header-job-queue/README.md)，不回填测试/原运行。

## 发送配置不是GOP的M

proxy入口8008a8b4在delay slot设a0=18h并调用8008a7d4。后者用80090090构造N，五个u16为`{18h,19h,4,2,1bh}`。8008a7f8/8008a800传同一N到8008933c；80089344先保存N，80089348→80087f04(a0+4,N)，再通过80083280→80080c98构造两个sender子对象。实际80080d00为`sw a1,11d8(a0)`，所以u32[sender+11d8]=N。

这不是先前GOP配置`{7,8,1b,2,4}`，不能借其字段值猜recipient。

| sender | 配置读取 | 结果 |
|---|---|---|
| 8008174c | u16[N+8] | cmd8407，endpoint1b |
| 800817d8 | u16[N+2] | cmd8421，endpoint19 |

80083698..ac给出直接身份证据：两次a0均为s6，两次a1均为s5=D。继承已证serializer801c61b4，body+10保留u32[D+10]。lookup分别得到1b→80ae3bc0、19→80ae3b40；这些仍是MCU内部地址，不作host pointer。

## Header19的receive与dispatch

静态记录80243ec4为`{a,0,0,80080a08,8,1000,8026bfa8}`；首worda不是endpoint。入口80080a08设置a0=19h，调用800901d4得到`{19h,18h,4}`；80080ad0传给80080548，按构造创建F=worker+8，并在80080a94..a98保存u16[manager+22184]=19h。

801c4f4c/50读该字段并调用8000cc28，801c4f5c用801aadac(endpoint19,-1)取message。80080880的opcode table基数为840d；8421项80218624的四字节20090880指向80080920。该分支保留原message为a1，将selected worker+8当F传a2，调用state vtable+18；已核state table8023c728+18=8007f974。8407小于table起点，不能接到同一条ring enqueue路径。

## Header种类与当前严格缺口

已证8007f748初始化body I=message+8后，s8[I+11]等于1或2时去另两个构造；两者都不等时才分配1644并调用801090c8，安装80240700、+c=80109288。不能把未知初始化值默认0来强选AVC。

在这些source条件下，可保留：

```text
D为prepared AVC B descriptor
 +已证proxy sender
 +dispatch到合法enqueue handler
 +初始化确实选择AVC header
  => same D --8421/endpoint19--> body+10 R
  => retained F ring => current Q为某个实际B
```

Q不必是刚发送D，不新增队列帧次序假设。

当前第一严格阻塞是selected worker：801c4fa0 MTLO s2、801c4fa4 word0082001c、801c4fac MFLO v1，再LW a0,2218(v1)。该word没有被当作乘加或NOP，因此未无条件证明选中哪个构造出的worker，更没有观察实际header选择。

E1（N构造和sender+11d8 store）→F1（两种cmd的不同recipient）；E2（receiver config/lookup/table）→F2（8421到header queue）；E3（same-D）→F3（条件B指针关联）。无条件actual_Q_equals_prepared_AVC_B及P/B geometry单位推广仍为NO，不新增猜测geometry代码。YC packing、原始帧消费与codec execution仍未闭合，capture=false。
