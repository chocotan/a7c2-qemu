# InfraBB OUT1 → VEF IN1：补齐连接前的静态契约

此边在`run-mfj5hx4k`的11条连接清点中明确拒绝。没有新增运行成功、像素或CP任务执行证明。
本记录复用此前只读代理已交付的结果，主会话进一步核对原始字节、格式producer和216B helper。
范围为原固件只读分析、本机隔离QEMU；本目录只保存公开研究工具与小片段证据。

CP原件SHA256=`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。
本文代码地址均为raw offset，CPVA=raw+108000。Kuna对ELF wrapper的合成VA可能是raw+400000，
必须先换算，不能与CPVA混用。wrapper的整个可执行section已与CP原件逐字节核对相同。

## 四包与状态

S=`{0,2,1,9284074a}`（InfraBB slot5），P=`{0,1,1,905a0048}`（VEF slot1）。
D取该run的AP动态reply/source SID。

| 路径 | 内frame/cmd/len/flags | 内容 | 外replySID | 总长 |
|---|---|---|---|---|
| AP→InfraBB | 1000/0001/28/2 | S,P | D | 64B |
| InfraBB→VEF | 1000/0100/28/1 | S,P | 0 | 64B |
| VEF→InfraBB | 1000/8100/30/1 | S,P,status,0 | 0 | 72B |
| InfraBB→AP | 1000/8001/20/2 | S,status,0 | 0 | 56B |

长度栏为十六进制。Get的InfraBB自replySID规则不能用于控制消息。
原0001 handler rawcdc16完整比较三u32，ce02c→5835ca；原8100 handler cdaf0→cdec2→5839a6。
后者直接恢复缓存请求，不使用旧VEF source路径的event8重入或第二组P比较。
VEF0100 consumer raw10c748按低u8找P，583818写peerS/state0并发8100。
S由state1→2/pending1→成功0/pending0，P由state1→成功0，两端完整peer分别读回。
只读state0不足以判成功，原helper失败路径也可能最终写state0。

## 格式producer与真正consumer

| Evidence | Finding | 实现前必须达到的Path |
|---|---|---|
| raw10c7e8从P index1选择ordinal0，发内部2002/f008 | producer是VEF，不是PinMem | 独立VEF currentinfo；不改原固件字段 |
| raw10ddb4检查目标pin state0，10ddfc→5eab40 | unit404实际分配，152B producer请求/source905a0048 | 有效handle/真实backing，拒绝空地址或零容量 |
| raw10de50..6a写SSYN与02000000，10de7e→5e0dce | 本路径头版本02000000，key0/16B payload，首条80B | 单独构建/解析，不能沿用仅接受01000000的pin_yc_decode |
| 原InfraBB表rawfe79ac为01000000000000008007000038040000 | cold payload为code1/component0/flags0/reserved0/1920x1080 | 原16B表与真实buffer逐字节匹配 |
| raw10de84→5ea88c | producer cmd25仅关闭open，不额外cmd21 share | 原分配owner引用保留并移交，不能伪增第二份owner |
| rawcdc90→d38b4，ce1e8..ce23c | InfraBB收到0104后实际打开/遍历SSYN/key0并比较 | 独立216B helper、有界解析、真实读回 |
| rawce244→d3a48；ce25c→d373c | 匹配后cmd25 close，再cmd23/opt0归还owner | 区分close与release，最后owners/opens/live归零 |

通知仍为80B：OSAL source905a0048→destination9284074a，内1000/0104/38/1，
body=P,S,unit404,handle,offset0,0，外replySID0。8001与后处理可异步交错，不能把8001当buffer-ready。

## 216B helper不能套152B实现

主会话直接复核的原Thumb指令表明：

- rawd38e6传消息长度d8；d38f2写cmd24，d38f6/d38fc写token55到+14。
  d38f8写handle@8及等待值@c；其入参用于此边的等待值是ffffffff，option@16是0。
- rawd38da→a3ccc(type2,owner284,0061003c−70000000)创建动态临时接收端。
  主会话进一步核a3ce0将type2 OR28得2a、a3ce8→45dd24；目标标志检查后a3d0c可能将
  创建的动态ID OR90000000。不能复用AP的8开头replySID，更不能将fixed9284074a当作同步source。
- rawd3960..3970要求回复cmd8024、token@6=55；d399c要求descriptor有效且size@20非零。
- rawd3a70同为d8，cmd25/token55；该producer没有初始化option，不对option做无依据的零限制。
- rawd3768同为d8，cmd23、token55、option取调用参数；此边匹配释放传0，不是旧PinMem路径的2。

现有本地`pin-buffer-wire.c`只接受152B，并将9059000e绑定creator、905a0048绑定consumer；
它不具备此边的动态临时SID、216B回复或creator-close/owner移交语义。
现有`pin-buffer-owner.c`的creator/share双引用政策也不直接对应本边：producer不share，
consumer需要接收原owner，且close之后还要独立release。后续应显式实现限定owner移交，
不能用先share后release冒充原wire或宣称已有计数等价。

## 复现字节核验

从项目根运行：

```sh
python3 final/a7c2-re/report/2026-10-17-qemu-native-camera/report/infrabb-vef-static/extract-evidence.py \
  --cp analysis/system/cpapp-b.bin \
  --wrapper analysis/qemu-boot-research/cp-emitters/cpapp-b.thumb.elf \
  --output final/a7c2-re/report/2026-10-17-qemu-native-camera/report/infrabb-vef-static/original-byte-proof.json
```

脚本拒绝错误CP摘要或wrapper section不一致，并断言长度/命令/token指令及原16B表。
该证据全为静态，尚未动态验收四包、216B helper、引用移交或非冷态分支。

## Kuna复核结果

`selected-kuna.json`定点导出5函数，均无per-function error：raw10c7e8、10ddb4、d38b4、d3a48、d373c。
Kuna提示这些入口位于自动发现的大函数内部，但按显式地址分别反编译；主会话已核每处原Thumb prologue，
入口选择有原指令依据。JSON的address使用wrapper合成VA=raw+400000。

输出再次确认ordinal0选择、SSYN02000000、unit404分配、cmd25关闭、216B消息长度、token55和
cmd24/25/23回复检查。Kuna将DMM目的常量0061003c渲染为字符串指针`"tingData"`，这是地址与数据
误分类；此处必须以原Thumb立即数及调用签名为准，不能据字符串推导协议目的地。
没有以“反编译无报错”替代原始字节，也没有据静态成功标记连接运行完成。
