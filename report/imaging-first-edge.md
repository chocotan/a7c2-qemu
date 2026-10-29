# 第一条图连接：InfraImaging OUT1 → InfraBB IN1

`run-509c5q1z`已通过这条默认关闭有限边：64B Connect请求、独立64/72B内部握手、sink业务标志一次写入并读回、实际DMM404映射缓冲、80B SSYN格式发布/解析、五字缓存更新及引用退役，最后唯一56B回复由原AP258/Common381消费rc0/fault0/ap1。本轮SD与退出双锁通过，592项联合回归/139子测试与独立限定复核通过。见[通过收据](imaging-first-edge-native-proof.json)。`imaging_first_edge_native_verified=true`只指这条虚拟控制/格式边，`capture_verified=false`。

## 为什么是这一条边

原 `run-2r73dber` 的Common381/PID258在消费三个InfraImaging Get后实际发13条连接，第一笔为：

```text
target=90050004 source=81cf61c4 bytes=64
c461cf81a0a0a0a0010040001800000040000000000000000010010028000200000000000200000001000000040005900000000001000000010000004a078492
source={type0,dir2,index1,owner90050004}
peer={type0,dir1,index1,owner9284074a}
```

该轮13笔连接都明确UNSUPPORTED；Get通过不代表连接通过。图planner沿错误路径继续发出302c，但其成像转换尚未完成。这里先恢复第一条实际边及其数据内容，后续边仍拒绝。

## 原件合同

原件仅为公开ALLLANG 2.01 cpapp-b.bin，SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`；下表地址为CPVA，`raw=CPVA−108000`。

| 阶段 | 原地址与内容 |
| --- | --- |
| source Connect | 46f1b0→68b5ca/68b6e6；full-u32首描述符查找，cold1→pending2，保存peer及原requester，发1000/0100 |
| peer Connect | 1d5d9e→68b818；cold1验证type/direction，复制source到peer、state0，回72B1000/8100/48/1，outer replySID0 |
| source completion | 46f43e→68b9a6；state0/清pending，向保存的requester发56B1000/8001/32/2，self/status0/trailing0，outer replySID0 |
| sink posthook | rawcec90（CPVA1d6c90），dir1/index1命中mask3fe；需要connected state0，申请DMM404 |
| sink业务标志 | CPVA1d614a/rawce14a原字节1154，成功接线时写`01acad0f[peer.index]=1`；本边index1→01acad10，原初值未知 |
| source format | 46ef52按**第二描述符**full-u32选择OUT1；46f1f8只支持输出index≤3，成功分支**不要求pin保持cold1** |
| cache | 46f52c..54c写五字，46f54e实际`movs r0,#0x21`；同步对象是十六进制21/十进制33 |
| Free | 46f560→b44b96(handle,5)→510fdc的23/option2；不是先25再release |

原peer回复和source AP回复可能先于格式后处理完成，若只按回复0宣称成功会漏消费。本有限profile保守地延后唯一AP回复，直到已证同步格式分支及Free结束；这是本地执行策略，不宣称原RTOS排程或时序等价。

## 格式确实流过数据

sink申请216B DMM command20（unit404、semantic owner284、option1、waitFFFFFFFF、token55），成功得到一个真实owned handle/open extent。它写入80B容器：

| 字段 | 本条边 |
| --- | --- |
| SSYN签名 / header+4 | `SSYN` / word06000000 |
| 项数 / 表偏移 | 1 / 20 |
| entry签名 / key / type | ETRY / 0 / **1** |
| 数据偏移 / 长度 / next | 40 / 16 / 0 |
| 16B数据 | `01000000000000008007000038040000` |

这与旧VEF SSYN01/type0不同，不能直接套旧packet。sink随后command25只关闭creator的open，owner仍活着；发布80B1000/0104/38/1通知，内容为peer描述符、source描述符、unit404、handle、offset0、trailing0。

source对该handle发216B command24 Open，读实际映射的80B、核全文摘要和结构，再复制16B并用原字段顺序更新五字缓存：

```text
初值  {1,0,0,0,0}       public rawfe1070；不是零BSS假设
新值  {0,1,1920,1080,0} component,code,width,height,full-u16-flags
payload FNV-1a64 = 1a3c540ebc5023bd
```

payload+4没有被原receiver消费，但仍纳入完整16B摘要。consumer不强限1920×1080或窄化u16 flags。该限定成功分支同步完成，无forward、任务投递、CMOS/ClkCtrl/帧处理；未扩展全局硬件独立性结论。

DMM生命周期在同一个既有8192B control reservation上继续，无reset/clone：

| 阶段 | owners / opens | 含义 |
| --- | --- | --- |
| allocate/write | 1 / 1 | creator持有并打开 |
| Close25 | 1 / 0 | 仅关闭，不能误当release |
| 成功通知移交 | 1 / 0 | **同一owner**转给consumer，不虚构command21 share |
| Open24/read | 1 / 1 | actual mapped extent读取 |
| Free23/option2 | 0 / 0 | 退役，旧handle失效、字节保留 |

原临时DMM endpoint由2a/owner284、owner5构造；本profile内部使用明确虚拟sender身份与同步provider，**不声称创建/执行了原CP任务**。请求/通知/回复消息的独立allocation/free与buffer reference是两条所有权链。

## 地址和资源边界

原5120f4从公开表cee7b0将physical500000000区间映射到CP80000000。ARM helper5feb94→611ddc→61b0c8还会查询CP页表属性并使用bit2；本次没有读回原CP页表。虚拟provider必须是原先已保留的physical500000000/8192B RAM，handle、generation、extent长度、物理地址、CP alias及消费范围全部相符才准入，不接受任意宿主指针。

同BB/ADF资源guard要求前置0323/0336/032d/0110已由原AP释放且没有busy/fault/retained，两个新边registry的Get回复已全部释放，当前pin仍是各自构造态，旧control事务已经完成并退役。foreign Speech405/406缓冲仍保持原owner/live/open，不释放、不重用。

新开关：

```sh
A7C2_IMAGING_CONNECT=virtual-imaging-out1-bb-in1-v1
```

依赖完整BB profile链与公开seed、单a0d候选、256GB目录SD、new UI/firstboot/自然快门/安全导出。host→guest为`MENU_IMAGING_CONNECT`，缺失时默认关闭；constructor核exact值并记录enabled/first_missing/初cache。manifest所有运行完成字段仍false，不能把意图当结果。

## 首轮原运行的部分证据与遗漏修复

`run-9rvjwhrz`/7fdba5 observer实际完成消息握手、mapped SSYN格式消费与Free，唯一56B回复由原AP258/Common381释放rc0/fault0/ap1；本轮双Fsysflush0/全树3文件SHA/cleancommit与owner175354/组/QEMU退出和双锁实际独占也通过。但对照下一type8边原指令时发现本边同样需要sink标志01acad10写1，初版遗漏了这一业务副作用，故**完整首边验收拒绝**。

该run的`imaging-first-edge-native-evaluation.json`明确分别保存AP消费=true、mapped control format=true、SD=true、sink_marker=false、full_edge=false，原日志/270冻源保持不回填。严格验收脚本为`runtime/analysis/scratch/evaluate-imaging-first-edge-native.py`，该run返回1符合预期。

父已补独立marker value/known/write-count、写入后读回和`PEER_MARKER_WRITTEN`事件（old_value_known0），在原成功peer返回后、格式posthook前执行；未对原CP RAM或原初值作断言。manifest增加固定地址/写入值/初值未知合同，源字节1154和成功测试事件顺序/计数都加入回归，592/139再次通过。补后新原运行为下节`run-509c5q1z`；旧partial保持不变。

## 完整首边原运行验收

`run-509c5q1z`使用observer `4b9e1c85b48fc6269d5c7510ee25626162f34501aaa2881e71f28f6d2f67eccf`，270冻结源，同一a0d候选。console SHA256 `9b856a35dee4e42dae689586608ee57ccb65cdfe570591b41e0be5b6dda69b6c`，同轮源归档 `f3dcead1c7af6e09e8838758868ad4ce83025ba944fc8971d14931102bfaac61`；gzip时间戳不同于build收据，按该run收据与归档内270文件摘要核验。

严格评价器在本run生成`imaging-first-edge-native-evaluation.json`并返回0；旧run9rv返回1。新run实际读到了：

- 原64B请求，独立64/72B peer消息、完整S/P字段和结果0。
- `01acad10`的虚拟投影一次写1/readback1、初值未知，位于peer回复后、格式写前。
- 216B四操作20→25→24→23的全部字节；真实pool handle8400/extent512/physical500000000/CPalias80000000，承接旧pool已退役的allocation1/release1，没有reset。
- 完整80B packet FNV `88d47938b00f682e`和16B payload FNV `1a3c540ebc5023bd`；实际mapped read/全文比较后，0x21对象下五cache为0,1,1920,1080,0。
- 引用1/1→1/0→1/0→1/1→0/0，7笔内部消息free0，buffer retired后才发布唯一56B8001。
- 原AP PID258/TID381对同一唯一回复指针free0/fault0/ap1；后继type8 Get及64B请求实际出现。

本轮两次原Fsysflush0，seq1452592138641146/1452593072624583，STOP恢复、host三文件与两export的尺寸/SHA全等、cleancommit；owner186080/其组与QEMU均退出、两锁实际独占，无SIGKILL。初始Speech强归属证明通过，foreign405/406继续live。host仍仅83B INPUT/database/XML，EE1/0/0，无JPEG/MP4。

独立复核e5f9无P1–P3：核270源、候选实体、52条原始引用、DMM四消息、actual readback/cache/Free、唯一AP消费、同SD全树，并重验新run返回0/旧partial返回1；独立确认无QEMU和双锁可独占。没有把这些证据提升为原CP/RTOS/页表/硬件或图像帧。

其余12条图连接与302c仍未完成。当前推进下一实际type8 `{8,2,0,90050004}`→`{8,1,0,9284074a}`，已源审为普通握手+独立sink标志、posthook检查后因index0退出，无DMM格式；新实现与验收另记。

## 测试及当前限制

- 新连接102个strict C11/Werror/ASan/UBSan场景，复用真实0323→0336→032d→0110前置、两个独立Get、显式byte-array映射fixture、原池历史与新handle世代、握手、实际backing坏字节/通知/DMM回复拒绝、8处分配错误、inline free、发送/释放失败、fork、资源忙和失败后不可重试。
- 格式23项测试核公开原字节、SSYN06/type1、16B消费、五字读回、未消费字段与全u16边界；pool新close/transfer保持旧双引用回归。
- 父联合33模块：592 passed/139 subtests。完整guest exports执行实际C constructor门禁正反例；原BB旧门禁继续覆盖。
- 独立审查发现P2：错误owner或底层free失败会留clean_completion1。父已在两故障分支锁内清零，并新增故障当下及成功恢复后仍false的断言；AP实际消费单列，不抹去故障历史。

首边控制/格式验收已完成；其它12条图连接、302c模块转换、EE启动、JPEG/MP4仍未完成。
