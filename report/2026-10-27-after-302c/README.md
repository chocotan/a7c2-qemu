# 302c之后：实际诊断运行与剩余成像工作

已完成多次实际批次推进：独立诊断302c → 有状态虚拟4073模式0 → 原4063/40f9消费与诊断402d → 原AP消费诊断4014/4057 → 原AP消费诊断409d → 原AP消费诊断4000和单向4072。最新 `run-nzx01uc3` 到达worker378的3003/24 B真实数据等待，EE仍为0，没有JPEG请求或JPEG/MP4。所有运行分别保存收据，诊断传输不等同原CP业务或拍摄成功。

用户授权本机隔离诊断，目标是尽快恢复原固件拍照录像。实验使用公开ALLLANG、候选QEMU、目录映射256 GB虚拟SD；不接真机或物理卡、不使用private/full-system资产。严格302c profile继续保留；诊断profile默认关闭，并与严格profile互斥。不直接改AP的EE、曝光、镜头holder或ready字段。

## 实际完成与证据

| Evidence | 已验证内容 | 限制 |
|---|---|---|
| E-host | 2332 passed、257 subtests；原libc2.25 ABI通过；observer `933f6347d5f01e68af2f6fc7965f15e0575fb0f5e84702d92b25bdbcb9343944` | 宿主自测与ABI，不是拍摄 |
| E-302c | 同轮全13 owner门禁通过、原3007回复实际释放，独立302c回复由原发送线程实际释放 | diagnostic_only=1；CP history/current/mode/module均未验 |
| E-next | 紧接着原AP发12 B `050073402700008000000000`，destination90030001/source80020002 | 4073尚未在此run实现；mode0来自byte+8 |
| E-EE | 快门后原 `7e67700` 四字节读回 `00000000`；JPEG_REQUEST未命中 | EE未提交，不能推断编码器故障 |
| E-SD | 同轮两次原Fsys FlushVolume=0、owner恢复、3份宿主文件大小/摘要一致、commit完成 | 仅INPUT、database、XML，没有照片/录像 |
| E-exit | 原host owner PID退出、无system QEMU、项目锁和卡锁均可实际独占 | 未使用SIGKILL |

选中initramfs SHA-256：`c31534519bcf5c884e7cde2fdaffdf965b3fdc760bdbcda965b5c93310c7e3b2`。运行收据位于 `runtime/analysis/menu-runs/run-tuafn8ou/cp302c-diagnostic-evaluation.json`，SHA-256 `9a33081e5a2206eb0f3258078ebe6adbdf06ee6545e2d7f779781925d210ca30`。该收据同时绑定本轮console、源码归档、回归和ABI摘要。运行私有输出不混入公开固件资产清单。

Finding F-next：诊断302c确实让原AP前进到4073；因此当前优先实现实际4073，而不是继续为本轮拍摄目标穷尽CP内部启动历史。

Path P-control（callflow）：原13图连接 → 真实3007/free → 诊断302c独立回复/free → **4073 mode0实际等待** → 后续配置/同步控制 → EE提交。后半段仍由静态路线和后续运行逐项核对，不能把列表中的命令预先当成已发出或已完成。

## 第二轮：4073实际消费，推进到402d

`run-j1cbs2i1` 的原AP PID258/TID381实际释放 `010073402700008000f00000`，rc0/faults0/ap_consumed1。内部虚拟D018 wire为 `050018d00000000000000000`，source90030001/destination90040193/12 B，sticky确实写1并读回；这不是原CP或原OSAL的D018交付声明。notification-off和无D013登记属于显式虚拟owner初始策略。mode1/2、pending完成和完整快照仍未支持。

该轮随后实际出现：

1. `4063`，2564 B；21个原审计分块完整重建，SHA-256 `ff6d35854ffeed873650d77ac8b7646b555883b338762306eb6d1120aacf7b74`。真实输入离线进入已交付C stager，190槽全通过且全部字节读回一致，semantic_applied仍false。
2. `40f9`，20 B。
3. `402d`，24 B，原wire `05002d402700008002000101010101000101010101000000`。

快门后Common381保存栈含完整402d请求，以及同一appFw映射还原的 `3535b04/354884c/34cb774/339f738` 返回地址。这是402d同步等待的强候选，不冒充正式unwind。EE读回0，没有JPEG_REQUEST命中。

构建前2370项测试/304子测试及原libc2.25 ABI通过；observer SHA-256为 `6a3fd2833bc5a8e7419e10cbddfd077066cf5e7abb2d5eff7b874b1912551841`。本轮两次原Fsys flush0/全树3文件摘要、owner退出、无system QEMU/双锁独占均通过。收据 `runtime/analysis/menu-runs/run-j1cbs2i1/cp-notification-native-evaluation.json` SHA-256 `203ad7e840cf59594600a60118ed5c032e14948f812f0f74cbb49cd4bec14cb3`；原GTK整体ok仍false，未提升成拍摄成功。

Finding F-4073：真实4073控制完成让AP继续发出整批配置并到达402d等待。Path P-next（callflow）：诊断302c/free → 有状态4073/d018虚拟消费/free → 原4063/40f9 → 原402d同步等待候选。下一实现以该实际402d为先。

## 第三轮：整批实现与统一自测，推进到4014

按用户要求，本轮先并行实现402d诊断传输、4063实际暂存接线、40f9局部配置消费，以及2040/JPEG输入接口，再统一测试修复。联合测试首轮138过/1失败，失败来自宿主fixture直接使用AArch64的gettid编号；修正fixture后，同批139项全通过。完整回归2451项/304子测试、冻结354份C/header/shell输入和原libc2.25 ABI通过，随后只启动一次组合VM。

`run-px07b5zs` 同轮结果：

- 原AP PID259/TID382发送的4063/2564 B、190个槽完整暂存并读回一致，FNV与原输入分块重建一致，原request释放rc0；未宣称190项业务已应用、未增generation。
- 原40f9/20 B的四个source-proven局部字段赋值并按known mask15读回，原request释放rc0；没有额外ACK、发布或硬件完成声明。
- 诊断402d的24 B请求完整保存，独立12 B回复的正文/source/长度由原AP释放钩子读回一致，sender=waiter=382、rc0/faults0/ap_consumed1。它没有执行未闭合的原格式业务、公共状态发布或generation更新。
- 原AP随后发出24 B `4014`：`050014402700008000000100010000000100000000000000`，同source80020002/destination90030001，当前未处理。EE仍0，无JPEG请求/照片/录像。

observer SHA-256为 `c53d707953db187273d6f53a84637be4b608c830659e414c353afcfaf819c633`，选中initramfs为 `01eaa5c8303998d97bb2345a8ebb57e89937ad9b91b31e7662de8e6edf494182`。两次原Fsys flush0/三份宿主文件摘要、owner退出、无system QEMU、双锁独占均通过。组合运行收据 `runtime/analysis/menu-runs/run-px07b5zs/cp-control-batch-native-evaluation.json` SHA-256 `4ecca02ca73fc7a3679da0d74c84f0202237cad4fa5df17ab45ed439680d4e44`。

Finding F-batch：统一实现和测试后，真实控制等待从402d推进至4014。Path P-batch（callflow）：原4073消费 → 原4063/40f9字节与局部字段消费 → 诊断402d传输/free → 原4014等待。2040/JPEG接口已自测，但仍无完整快照provider、实际像素解释或压缩硬件接线，不得计作快照交付/编码完成。

## 第四轮：三控制统一实现测试，实际消费4014/4057

下一批将4014（24→12 B）、条件40c8（328→12 B）、4057（12→12 B）实现为一个有限诊断owner，每opcode一次独立lease，前一reply必须由自己的原sender释放后才接受下一条。联合72项通过；含JPEG内存引擎的完整回归2474项/304子测试、357冻结源和原ABI通过，再启动一次VM。

`run-ktnudlyz` 实际看到原AP259/TID382先后释放4014和4057的12 B回复，rc0/faults0/ap1，正文/source/长度读回一致。40c8在该场景未发出，只有实现和自测，不能标为原运行消费通过。之后原AP发单向40ed，再由并行worker379发 `409d/12 B`，wire为 `05009d402700008000000000`。保存栈含该完整请求及appFw3535b04/3545970/34cbb74/338e9f8、futex98，作为实际409d等待的强候选，非正式unwind。

本轮observer SHA-256 `0702119825c04929d4a7f77ebdafd9a5150ebd1eea407d07c1e28b29946a2815`。双原flush0、3份host文件摘要、owner退出、无system QEMU/双锁独占通过，EE0、GTK整体false、无JPEG/MP4。收据 `runtime/analysis/menu-runs/run-ktnudlyz/cp-startup-controls-native-evaluation.json` SHA-256 `089b7a41434641ad4ed7426385fef876dfb79634ee3448207f91e470116e2b14`。

剩余EE控制的源检查已区分：409d可提供显式诊断12 B控制回复；4072是单向输入，不产生ACK；3012有12 B控制回复。3003要求16 B回复，尾部四字节来自CP状态记录，AP会复制和记录；其业务含义/虚拟取值未闭合，不能把它称padding或填零成功。下一批实现会在这个真实数据边界前保留拒绝。

## 第五、六轮：实际409d→4000→4072，到3003数据边界

EE控制批次先联合自测80项、完整2490项/304子测试/360冻结源及原ABI通过。运行前曾在leaf runner重复else处发生语法失败，未启动VM；原脚本/日志保存在 `scratch/cp-ee-controls-pre-VM-launch-failure/`。补真实leaf导入自测并把上下runner/validator也纳入冻结，v2收据独立保留，没有覆盖旧失败证据。

`run-a547uk6q` 的原AP258/TID378实际释放409d诊断12 B回复，rc0/fault0/ap1。前驱TID381与后继378不同，父guard仍验证每对自己的sender=waiter/同PID真实free，不放松原释放证据。接下来实际出现4000/20 B，而非按旧静态候选直接到4072；原完整wire、保存栈3546014/3389214/338ea00与futex98指向该等待。收据 `cp-ee-controls-native-evaluation.json` SHA-256 `0e423fe7873c430a950be5d5ec17cbd4bd50d3af3b58202f135abc2d5d6f892d`。

随后把[4000 set_movie_format](movie-format-contract.md)和SOS适配合成一批：联合104项、完整2514项/304子测试、363冻结源/原ABI通过；observer SHA-256 `54008e413435a7d5f85e6fc8b009c2088fa85db52c8df522cb2ad7359c376d8b`。

`run-nzx01uc3` 同一轮实际通过：409d原AP释放→4000原AP释放（12 B `010000402700008000f00000`）→4072单向原request释放。4000七个非连续输入字段实际读回为5,1,0,0,0,0,1，mask7f；4072两字段mask3读回、原free0，reply/ACK=none、queued0、reply_freed0、AP回复消费标志0，未把单向接收冒充回复。

原AP随后发3003/type0/24 B：`000003302700008000000000000000000000000000000000`；保存栈含完整包及3535b04/35460a8/34cb834/338ea60、futex98（非正式unwind）。这里需要16 B回复，尾四个状态数据的runtime provider仍0/4；没有缩包或填零成功。3012仍未实际出现，只有实现/自测。

本轮EE0、无JPEG请求/媒体产物，双原Fsysflush0、3个宿主文件逐字节摘要、owner/PID组/session退出、无system QEMU、双锁独占、GDB正常detach通过。收据 `runtime/analysis/menu-runs/run-nzx01uc3/cp-movie-format-native-evaluation.json` SHA-256 `9915c5e6dcf5b6004f2bcfc0f8a9d9b415812de8f345a3cff4d1b5fba428719e`。

[3003 source pins](cp3003-data-source-pins.json)已核5窗口790 B：前三字节来自root172fe50+3ec6/3ec7/3ec8（RAM1733d16/17/18），原root构造函数没有为这三字段提供已证默认来源；第四字段是a9885e计算及M/C覆盖选择，输入/历史仍缺。BSS清零、ACK、optics或4063暂存都不能替代这些来源。

## JPEG压缩组件与原硬件边界

[有界内存JPEG引擎](../virtual-jpeg-engine/README.md)已完成，使用已安装libjpeg-turbo读取真实RGB888 scanlines，向调用者限定buffer输出baseline JPEG；16项测试及C sanitizer组通过，独立解码和图像内容变化检查通过。测试只在内存中进行，没有写宿主JPEG来冒充固件照片。

[光学→JPEG集成](../virtual-imaging-jpeg/README.md)又有4项实际像素/独立解码测试：[SOS后段适配](../virtual-jpeg-sos/README.md)有11项严格C/sanitizer与独立重组解码测试，只有baseline帧/量化/Huffman/restart/SOS参数匹配才提供FFDA..FFD9借用视图。参考prefix当前来自真实host引擎，尚未取得原guest prefix，不宣称已兼容原硬件。

[原JPEG硬件前沿](../jpeg-hardware-frontier.md)已找到输入/输出DMA、长度FIFO和SOS输出要求。官方DTB和原map_io证明device0物理MMIO=f3020000；[原IRQ注册与GIC域](../jpeg-irq-routing/README.md)证明Linux/INTID61..65对应QEMU外部29..33，EOIR=f13a2010。45是syncsel而非IRQ。仍缺原输入分量顺序/plane/实际lease、原表的SOS适配，以及guest使能/target/状态/IRQ/DMA/Fsys实际消费。内存引擎完成不提升guest像素消费或capture。

## 实现与验收顺序

| 阶段 | 当前实现/证据 | 下一步及工作量判断 |
|---|---|---|
| 302c诊断传输 | 默认关闭的独立owner，真实3007/free和全13门禁，原AP消费通过 | 已完成限定诊断；不提升原状态等价 |
| 4073 mode0 | 有限虚拟notification-off owner/d018 sticky消费；47个sanitizer场景；原AP实际释放0通过 | 本限定分支已完成；mode1/2、pending/full snapshot另验 |
| 4063整批参数 | 190个固定槽解析和全字节暂存；已用原输入离线自测，并在组合VM实际复制/读回/释放通过 | 全部业务handler尚未实现，semantic_applied=false；不得仅复制就增generation/发2040 |
| 其余控制与快照 | 4014/4057/409d/4000诊断回复已实际消费，4072单向实际free/无ACK；条件40c8和3012只自测 | 当前3003/24 B等待，需要16 B含四状态字节；provider0/4，mode1完整2040仍缺，不能空填 |
| EE与第一帧 | 原AP提交点已定位；当前EE=0，CMOS测试源已有真实字节和lease但格式为测试协议 | 需要原帧描述符、像素布局、发布/回收和真实consumer；控制成功不自动完成这一阶段 |
| JPEG | Without_Pin走原硬件；内存引擎16、光学集成4、SOS适配11项通过，MMIO/IRQ编号源合同已闭合 | 仍须接原guest像素/lease/SOS表/实际IRQ/DMA/Fsys；组件可编码不等于固件已拍摄 |
| MP4 | 尚无原录像产物 | 先完成一帧/JPEG，再补连续帧、编码、时间戳、mux和封口；不能以主机录屏或独立生成文件代替 |

短期可完成的是逐个实际控制等待和有界数据decoder。完整成片的关键风险集中在完整状态快照、真实帧输入与编码器，不适合承诺仅补几个ACK就能完成。每次运行只有在消费者读取了实际内容后才提升对应功能状态。

## 运行诊断

从本成果目录执行：

```bash
cd runtime/analysis
python3 -B scratch/validate-cp302c-diagnostic.py
python3 -B scratch/run-hdmi-observed.py --cp302c-diagnostic
```

验证脚本以独占新收据文件保留结果；同名收据已存在时会拒绝覆盖，应保留旧结果并使用新的实验文件名。runner要求源码、构建、回归和ABI摘要一致，启动唯一一台VM，保存选中镜像，保留原UPM内核收据和目录SD退出保护。

已完成的4073实验使用独立profile `virtual-cp-notification-mode0-v1`，只有诊断302c完整消费与全13门禁可用才准入；其运行验收保存在独立 `run-j1cbs2i1`，未回填 `run-tuafn8ou`。旧严格302c拒绝run `run-wsefr5ai` 同样保留失败结果。
