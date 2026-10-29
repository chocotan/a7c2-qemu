# CP302c authoritative state frontier (bounded source-only result)

> 后续源码更正：原外层对3041不准入时，可由独立producer `b22788`直接发送专用302c/f000，不执行observer/perform、中央start或模块转换。本文的6/8与module门槛只约束正常转换分支，不能推广为全部302c回复的必要条件。见[两条完成来源合同](cp302c-no-transition-contract.md)。新不转换后端同样要求有效source状态与输入历史，不能无条件回成功。

`302c_native_verified=false`; `capture_verified=false`. 本次只读官方 CP 与既有源码/运行日志；没有 VM、网络、相机、私有配置或完整系统路线，没有改动现有 C/H。原 CP SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，18090880 B。下文地址均为 CPVA，raw=CPVA−0x108000；CP RAM 地址不适用该减法。

复用既有 `runtime/analysis/menu-runs/bb-mode-tests-20261026/cp302c-transition-source-pins.json` 的 normal chain、reply producer 和八段 dispatch pins；不重验 all13 图、不新增回复。

## 已核实的对象边界

- 302c 内部请求实际是 3041。它查询的 current 是 CP RAM `u32[0x1a52ad4]`，getter `0xb1f2f8`。这是中央 sequencer 的状态枚举。
- `0xb1f140` 先读 busy `u8[0x1b1df9a]`，镜像到 `0x1b1df9b`；空闲时以 current 和 command 查 `0x1725858` 指向的 320 项命令表。表的实际来源由 `0xb1ef4c..56` 绑定，getter `0x8dd69e` 返回 `0xd97468`，`0x8dd6a8` 返回 0x140。
- 对 3041，表中仅两项：`0xd97d08=(6,3041,8dd8d1,3041)`、`0xd97d38=(8,3041,8dd8e5,3041)`。各 getter 返回 `0xeda542=01007700`、`0xeda54a=01007d00`。不能拿 0、mode3、BB word1、ADF phase 当成 6/8。
- `0x4b2a56` 取 path 末项，写 target `u32[0x1a52ae4]`；`0xb1f238` 只有经 `0x4b2b54` 当前 boundary 所选 module mask 检查和 path-end 条件后，才写 current=target。相关 generation `0x1a52ad8`、command `0x1a52adc`、intermediate pair `0x1a52ae0/2ae8`、ended command `0x1a52aec`、phase flag `0x1b1df9d` 是独立字段。
- 原 request actor 构造器 `0xb21604` 设置 vptr=`0xe77f08`，但它的 `self+0x18/+0x28/+0x30` 不是上述 global current。实际 aggregate 构造 `0xb1fb7e` 以 aggregate+0x108 调此构造器；不得混用 BB/ADF 对象的同偏移字段。
- sequencer 初始化构造器 `0xb1f328`（构造表 `0xfff418` 存 `0xb1f329`）只显式清 `0x1725858` 的 20 B 和 `0x1a52a88` 的 requested/returned 等结构，范围止于 `0x1a52ad4` 之前。它不能单独证明 current 被置 0，亦不置 6/8。初始 RAM 装载/清零与其后的完整启动 writers 仍待绑定。

## 本轮实际前缀

`runtime/analysis/menu-runs/run-ouc1t64_/console.log` 第 2793–2797 行：原 tid340/source810261c7 发 24 B 3007，现有模型 ticket1、mode3、generation1、current0、group3、pending_modules1f7e；原 AP 释放独立 reply，rc0。这是已有有限控制模型的消费，不是原 CP 全局 current 的读回。

第 14713–14714 行为本轮原 tid381 的 type0/302c、24 B、source80020002、opaque80000027：`00002c302700008000000000000000000000000000000000`，当前 endpoint 明确 unhandled/delegated。本报告不能将先前 3007 的 mode3/cold current0 迁移为 302c state6/8。

## Variant 来源的新证据

原 `0x3668f4` 以 `0x510728` 读取六个 4 B Backup key。`0x366920..2a` 的第三项是 `0x000300a7`，写入输入向量+8。`0x366998..b0` 遍历 62 个构造函数，传入该向量。`0x8dcb30` 用 u32[input+8] 索引 `0xd95bf0 + index*16`，复制完整 16 B transition descriptor。三项都是 8→7d：index0/1 含 module2 的 0323/032c，先 boundary8004 后0302，最终817f；index2 跳过该 module2，最终817b。本调查定位了 selector 的原读取链；父会话随后独立核得本轮显式虚拟 CP 数据源的 key 值为 0，见下面补充。原 CP 实际装载/执行仍未证明，禁止把该值当全局 current。

## 当前结论与实施门槛

尚不能建立 authoritative current=6/8 的完整历史。未来应从已证初始化与逐笔实际消费生成一个有限中央 sequencer owner，保留 current validity、busy、generation、command、path/target、requested/observed 及 history completeness；不要新增 set_current(6/8)，不要从独立图 callback 补中央状态。缺失启动输入、未知 writer 或仅见 send/delegated 时保持 unverified。即使起态/variant 被闭合，module mask 与 family1 phase1/3 observer 消费仍是独立门槛；不得据本报告发送 302c/f000。

## 最小可证的起态生产路径与未闭合的启动边

下表是原命令表/原 path 的静态事实，不是本轮执行历史。所有转换必须走相同中央 sequencer 的 start/prepare/module/boundary/commit；不能用独立图连接 callback 代替。外部 3000、3003、3007 分别生成 family0 event0、2、4，慢路分别进 `0xb218bc`、`0xb21898`、`0xb218a4`；三者最终经 `0xb21702 → 0x4b6958 → 0x4b28d8`。

| 已知中央 current | 实际中央命令 | 命令表项 CPVA / path CPVA | path 目标序列 | 对本次 302c 的意义 |
|---|---|---|---|---|
| 0 | 3000 | d97478 / eda42e | 8 | 可生产 state8；本轮前缀未见该输入/消费 |
| 0 | 3003 | d97468 / eda18e | 2 | 可生产 state2；还不能进入 3041 |
| 2 | 3011 | d97698 / eda120 | 0b → 2 | 3011 是返回 2 的操作，不能由它单独推出 state6 |
| 2 | 3007 | d976c8 / eda126 | 6 | 可生产 state6；与旧 cold 模型 current0 的 3007 是不同输入状态 |
| 0 | 3007 | d974b8 / eda43e | 57 → 0 | 当前有限模型选择的路径；不能转写成 6 |
| 6 | 3000 | d97c68 / eda15e | 8 | 即便曾到 6，也须继续追踪后续命令 |

`0x4b28d8` start 维护 busy/generation/command，并从实际 current 查 path；`0x4b29e0` prepare 根据 path 和本次 generation 准备 requested。module returned 经原生产者写到 requested 对应的独立 returned 槽；`0xb1f1cc` 周期处理在 boundary 成立后推进，`0xb1f238` 提交 target。表有更多状态及条件 getter，本表只列最小已固定路径，不是完整可用状态机。

**初始化仍缺一个具体源边：** `0xb1f328` 的构造表项已找到，但它未覆盖 `0x1a52ad4`。全原件的显式 MOVW/MOVT 取址扫描仅找到该 current 的读者及 `0xb1f238` 提交写者；这不排除 BSS 清零、scatter/load、基址相对或批量 store。扫描不授权宣称“唯一写者”，也没有证明原 current 的初始化值。原 aggregate+108 的 actor 构造器把自己的 +30 清零，绝不能据此宣布中央 current0。

因此没有证据将 mode3 的“3”变成中央枚举6，也没有证据证明 startup 内部流程未经过其它中央转换。AP 日志里看不见 3000/3003/3011，不足以排除 CP 自己的初始化调用。下一源码调查必须从 `0xfff418` 构造表的执行者、中央 current 所属 RAM 区的实际清零/加载边，以及 `0x4b28d8` 的非 AP 调用者建立初始化与提交顺序；不能只给 current 填一个 ROM/BSS 推测值。

## 本轮前缀能证明什么

console SHA256 `bc3723e5915bef0ed73d87251504a5f685846913ad4ad89ad9340d29d9cf097c`。目标前能见 30 条 background UNHANDLED，均 type5；唯一已消费的 type0 是 3007。随后目标 302c 是该观察链首条未处理 type0，晚于它的 3006 在第15811–15812行，tid340/source810261c4，不能倒序用来生产本次 state6。父会话独立提取全 run 为32条 UNHANDLED，包含目标302c与更晚3006；与这里的目标前30条相容。

30条 type5 的有序 opcode 为：`40b8,402a,40af,401c,404e,4043,4070,4028,409c,4022,4023,4023,4084,4084,40fb,4084,4084,40fb,4028,4051,40c5,4102,40ed,4139,4177,40d1,4022,40b8,402a,40af`。不能仅据 40xx 编号就证明它们全部不影响中央状态；本轮没有逐个关闭其 receiver/callee writer，因此它们作为原 CP 状态历史的保持边仍是未证。它们在现有虚拟端点中仅 delegated，不更新当前有限 `cp_cold` 对象。

此外11条 403d 被独立 release service 处理，可见其请求四word和返回0；它们没有 background 原始 byte 收据。原 `menu-observe.c:7544` 仅对 4..64 B 写完整 raw，因此 184 B 的 4139（第2788行）只有 opcode/source/size，**没有正文**。`cp-background-device.c:125..136` 的 UNHANDLED 日志也不复制正文。不把缺正文的一笔重放为 no-op，不把委托/发送返回当原 CP 模块消费。

日志足以证明当前有限模型在 3007 后 current0、hardware_ready0。它不能证明原 CP 在 302c 前为0，更不能证明为6/8。旧 cold profile 的 pending_modules1f7e 仍保留，控制 boundary 完成不等于所有模块完成。

## Selector 已闭合到显式 CP 数据源，未闭合到原 CP 执行

父会话独立读取公开 BK4 与本轮导出文件后提供以下内容型证据；本子任务没有打开导出的 SETTING 文件，也未改写父会话的 key pins：

| 输入 | 身份与值 | 证据范围 |
|---|---|---|
| 官方 seed-backup.bin | full SHA256 `3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`，CP bank 文件起 ed000；key000300a7 位于文件11ece0，实际长度4，bytes00000000 | 父会话独立 BK4 解析；AP bank 中该 property 不存在，不可取其缺项为默认0 |
| 同 run 导出 SETTING/Backup.bin | full SHA256 `86678b79f362da046debf5b05504d6ad652b192852755feea15e73c4a303d87d`，两 bank checksum 均通过；CP bank key000300a7 为同样4B零，AP不存在 | 父会话同轮内容证据；不等于原 CP RAM loader 已执行 |

本次新增静态源链把它与真正读取者相连：

1. `0x55df9c..55e004` 将调用方 BK4 指针写入 RAM `0x1a7e85c`，验证 BK4，建立 `0x1a7e860` section 表与 `0x1a7e864` property 表。既有 `INIT-DISPATCH.md` 已证 BACKUP_INIT 入口来自初始化表；04000000 的有效原装载是其仍开放的边。
2. `0x510728 → 0xbe91ea → 0xbe9130` 是正常 Backup read 路线，使用上述 primary root；没有 AP bank 搜索或缺项默认零。`0xbe98c6` 经 root 的 section/property 表查完整 key，越界/未映射返回 null；`0xbe9184` 缺项返回 -1。命中时 `0xbe995c` 取真实长度，`0xbe9990` 算 root+payload offset，再由 `0xbe917e` 复制真实 payload。`0x51073e` 检查返回长度是否为期望4；错误路径诊断，不填造零。
3. `0x366900..36692a` 产生 key000300a7/read size4/输出向量+8，`0x366998` 把向量传入 descriptor builders。builder `0x8dcb31` 是 `0xd97370` 指针表 index37；产物在 RAM `0x1871618`，不是 ROM 三项中的固定板型别名。
4. `0xb1ef5a..72` 初始化 descriptor manager，把 RAM表 `0x1870468` 与数量0x134绑定；**另一张** command map 是 ROM `0xd97468`/数量0x140。这两张表不能互换。

未来显式虚拟 CP owner 若绑定并验证的是同一 CP bank，正常 read 返回4且 payload为上述零，可合法得到 selector0；缺失/长度错误/其它 bank/未绑定则保持 unknown，不能走错误默认。此条件只关闭 variant，仍不生产 state8。

| selector | 原 descriptor | module sequence（hex u16） |
|---|---|---|
| 0 | d95bf0 → ed8fe4/15 words | 011a 0202 0323 0405 0502 0602 0702 0920 0a00 0b10 0c02 0d00 8004 0302 817f |
| 1 | d95c00 → ed9002/15 words | 011a 0202 032c 0405 0502 0602 0702 0920 0a00 0b10 0c02 0d00 8004 0302 817f |
| 2 | d95c10 → ed9020/12 words | 011a 0202 0405 0502 0602 0702 0920 0a00 0b10 0c02 0d00 817b |

state6→77 的已钉序列与 selector2 的字相同，但 current/target/descriptor 依然不同，不能共用“起态已知”的判据。

## 下一次最小 API 与观察需求（建议，未实现）

仅扩展当前 background owner，不建立新通用框架，也不在 all13 身份检查点后改旧 C/H。本次已有源文件的关系为：`menu-observe.c → native_cp_background_dispatch → cp_cold_create(3)/begin/tick`；另有 BB/ADF/UDATE owners，它们未实现中央 start/commit。

- 在进程 constructor、任何 CP background 输入之前创建一份 `cp_background_history`，PID/generation绑定；重建原 actor 已知构造字段，中央 current 的 valid 位单独保留 false，直到真正的 source initialization 边闭合。禁止任意 initial_current 参数与 set_current API。父进程继承不能当子进程历史。
- 建议 `cp_background_observe_request(owner, source, bytes, size, producer_site)`：仅记录完整输入与连续 ordinal，区分 send/handled/delegated/consumed。覆盖所有 destination90030001 类型、原始 byte1、opaque、完整尾部；对184 B等长消息分块记录并标 total/offset/bytes_complete，而不是≤64 B截断后称完整。记录发生在任何 endpoint 早返回之前，使403d也有完整历史。未知输入使相关字段 knowledge 失效，不造 target。
- 将未来中央转换实现限制为 `cp_background_begin(owner, command)` 与内部 source-derived module tick/commit；begin 只能从 owner 当前有效状态查表，target 由原 path 产生。`0x1a52ad8/2adc/2ae0/2ae4/2ae8/2aec` 与 busy/phase flag分别归该 owner，commit 只能由实际所选 module 消费及 boundary 判据触发。snapshot 暴露 validity/history ordinal，不接受外部“模块已相等”或 state6/8 setter。
- 与源初始化边并行补充：原 AP producer_site/module调用点与 input ordinal，同步服务原 reply/free；每个真正中央 begin/prepare/commit 的 command/generation/path/target/current；每次 module requested/returned 的**写入 producer**，以及 source-backed Backup binding/read 的 key/size/result/bytes。仅观察 AP send 无法捕获 CP 内部 startup，故本地 source-derived startup engine 的内部调用也必须进入同一 owner 历史。

这些字段使下一次 run 能回答具体的“哪次初始化/命令写了 current、是否在本次302c前已提交”，但一次原始 send audit 本身仍不能解决未模拟的 CP 内部启动。没有初始化 writer 前，继续报告 source current 未证，不为了试通302c选择6或8。

## Evidence → Finding → Path

| Evidence | Finding | 下一闭合边 |
|---|---|---|
| E-state：b1f328/fff418、b1f2f8、b1f238；command-map d97468 | 中央 current 与 actor/BB/ADF 各字段域不同；已定位提交写者，初始化未闭合 | C运行时/loader清零与构造表执行者 → 首次有效current → 真正中央start调用 |
| E-prefix：同轮 console 摘要与2793..2797、14713..14714、15811..15812 | 已有3007有限控制为current0，晚3006不能倒推本次6；184B正文缺失 | 从进程构造开始完整输入审计 + 内部commit ordinal |
| E-variant：3668f4/8dcb30、55df9c/be9130/be98c6/be9990 + 父会话BK4内容 | 显式同源CP bank可选variant0，非default/固定板型 | 绑定该CP数据源正常read4 → descriptor0，独立保持state与module门槛 |
| E-path：d97468/d97478/d97698/d976c8及固定path | 生产6与8需要不同中央转换；3011不直接生产6 | 逐笔实际中央begin/module/commit，不能从图回调借状态 |

结论：variant来源及有限显式输入值已收敛；本次302c之前的 authoritative current历史仍未闭合，302c/f000与拍摄继续false。没有新增生产代码、消息成功、VM运行或原CP执行声明。


## 可复核原字节附录

仅对上述固定原件运行，从本成果根目录使用下述 Python；它只读 CP 并核对本文 pins，不执行固件。CP RAM 地址不在此数据字典中。

```python
from pathlib import Path
import hashlib
d = Path("runtime/analysis/menu-root/cp/cpapp-b.bin").read_bytes()
assert len(d) == 18090880
assert hashlib.sha256(d).hexdigest() == "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"
pins = {
  "0xb1f328": "80b56f4645f658001421c0f27210fff6e4e442f688200021c0f2a510c0e9001101720c304021fff6d8e4",
  "0xfff418": "29f3b100",
  "0xb21604": "47f600710122c0f2e70108310160002181740182c1608183c0e905118277024680f82c1080f82d10016380f8241080f8231080f8201080f8251002f81f1fd17091707047",
  "0xb1f2f8": "42f6d420c0f2a51000687047",
  "0xb1f21e": "42f6e42042f6d4214df69c75c0f2a510c0f2a511c0f2b11500680860",
  "0xb1ef4c": "45f658002946c0f2721000f05cfa47f4cbf4bdf5fffe0546bdf501ff024620462946bde8b04000f0efb9",
  "0x8dcd60": "40f26840c0f2871070474ff49a707047",
  "0x8dd69e": "47f26840c0f2d90070474ff4a0707047",
  "0xb21898": "416043f203010022fff72fbf416043f207010022fff729bf416043f22f010022fff723bf41604ff440510022fff7",
  "0x4b28d8": "f0b503af4df8048d4df69a760446c0f2b1163078012811d10720214600226ef27bf204204ff20201",
  "0x4b2b54": "80b56f46017ae9b1c168426931f812e01ef4004f03d10ca091f205f512e000224ff0010c0cfa02f313ea0e0f05d000eb4203598e1b8b8b4204d101320d2af1d3012080bd002080bd",
  "0xd97468": "000000000330000083cf8d00033000000000000000300000afd68d0000300000",
  "0xd974b8": "0000000007300000cdd68d0007300000",
  "0xd97698": "020000001130000099ce8d0011300000",
  "0xd976c8": "0200000007300000a3ce8d0007300000",
  "0xd97d08": "0600000041300000d1d88d0041300000",
  "0xd97d38": "0800000041300000e5d88d0041300000",
  "0xeda18e": "01000200",
  "0xeda42e": "01000800",
  "0xeda120": "02000b000200",
  "0xeda126": "01000600",
  "0xeda43e": "020057000000",
  "0x366900": "04ae2fa40422c0f20305314623462846a9f10aff681c311d04222346a9f104ffa81c06f1080104222346a9f1fdfe",
  "0x36695c": "46f2104c40f2684e0020c0f2d90cc0f2871e0ceb00030eeb0006103093e83600b0f5766f36c6f4d147f270390ef576660025ea460df11008c0f2d90959f825205046414690475146b4461036013591e81d003e2d8ce81d00f0d10ab0bde8",
  "0xd97404": "31cb8d00",
  "0x8dcb30": "80b56f46896845f6f032c0f2d90202eb011191e80c5080e80c5080bd",
  "0xd95bf0": "080000007d000000e48fed000f000000080000007d0000000290ed000f000000080000007d0000002090ed000c000000",
  "0xed8fe4": "1a010202230305040205020602072009000a100b020c000d048002037f81",
  "0xed9002": "1a0102022c0305040205020602072009000a100b020c000d048002037f81",
  "0xed9020": "1a01020205040205020602072009000a100b020c000d7b81",
  "0x55df9c": "80b56f464ef65c0100f10c0e002342220ff2600cc0f2a71108601ef80310d2b2914223d10ceb0302591c527803290b46f3d14ef6600200f58071c0f2a712116010f810cf43788278c0784cea032342ea002043ea004000eb400001eb40004ef66401c0f2a71108600020",
  "0x510728": "f0b503af4df8048d82b0984614460546d8f257f50646a64206d006a041462a463346009433f215f7304602b05df8048bf0bd",
  "0xbe9172": "304600f00cfc014640462a4635f646e201e04ff0ff352846",
  "0xbe98c6": "4ef65c01c0f2a711096811f810cf4b788a78c9784cea032342ea012143ea0142010c914235d24ef6600201eb410180b2c0f2a712126812f8113002eb41014a7843ea0222904224d211f802cf4b788a78c9784cea032342ea012143ea014108444ef66401c0f2a71100eb4000096801eb40000246c17812f8023f43ea01219378d27843ea022241ea0241013108bf0020704700207047",
  "0xbe9990": "10f8021f42788378c07841ea022143ea002041ea00400021b1eb106f08bf0421ff22b2eb106f4ef65c0220f07f40c0f2a71208bf02211268104408447047"
}
for address, encoded in pins.items():
    expected = bytes.fromhex(encoded)
    start = int(address, 16) - 0x108000
    assert d[start:start + len(expected)] == expected, address
print("verified", len(pins), "source byte spans; runtime current/capture remain unverified")
```
