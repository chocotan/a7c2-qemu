# AP 原提示音发送路径：032b 的静态合同

本次仅做静态原字节核对，没有播放完成或宿主出声证据。

样本为公开导入的 `runtime/analysis/menu-root/usr/lib/appFw.so`，99960744 B，
SHA256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
所有地址均按 ELF PT_LOAD 转换；本文列出的代码与字符串在 VA=fileoff 的段中。
不能把这个关系推广到第二 PT_LOAD（该段 VA=fileoff+0x10000）。

## 已证实的调用链

录像开始处 `0x3485b74 → 0x34c7d98 → 0x34f2f84` 构造 `0x200d/0x032b` 请求。
与日志字符串的关联为：

- `0x3485b80 a0be00d0` / `0x3485b84 00481e91`：ADRP+ADD 得到
  `0x4c5b792`，字符串 `Failure MSGID_START_SYSTEM_SOUND_CMD(BEEP_ID_REC_START)`。
- 调用前 `0x3485b58 a0008052`：`mov w0,#5`，写输入的第一个 word。
  同时输入 `+4:u32=1`、`+8:u8=1`。
- 停止处 `0x34b05c0` 调同一包装器，参数第一个 word 为 6；
  `0x34b05cc/0x34b05d0` 得到 `0x4c60f09` 的 REC_STOP 失败日志。
- `beeplist.txt` 原索引匹配 `0x0005=BEEP_ID_RECSTART`、`0x0006=BEEP_ID_RECSTOP`。

对可执行 PT_LOAD 的对齐指令扫描发现包装器 `0x34c7d98` 的 9 个直接 BL 调用点：
`305e53c, 308a854, 33b1444, 342bbd8, 3473f3c, 3474300, 3485b74, 349b9e0, 34b05c0`。
这是直接调用范围，不排除间接调用。最终构造器 `0x34f2f84` 的直接 BL 调用点为
`0x34c7dc0`。因此不能只用录像的两个调用点解释所有提示音。

## 16 字节 wire 布局

构造器 `0x34f2f84` 的输入为 x0 指向的参数，x1 指向结果 word。
令 `D=sp+0x40`，首先 `0x34f2f9c bf7f04a9` 对 D 的 16 字节清零。

| D 偏移 | 宽度 | 写入值 | 写入指令 VA / 原字节 |
|---|---:|---|---|
| +0 | u16 | frame `0x200d` | `34f2fa0 a1830079` |
| +2 | u16 | cmd `0x032b` | `34f2fa8 a1870079` |
| +4 | u16 | 总长度 `0x10` | `34f2fb0 a18b0079` |
| +6 | u16 | flags `0x8001` | `34f2fb8 a18f0079` |
| +8 | u8 | `1` | `34f2fc0 a1230139` |
| +9 | u8 | 保持零 | 前述全包清零 |
| +a | u8 | 输入 +0 的 u32 低 8 位（两个REC调用分别为5/6；编号域未闭合） | `34f2fc8 a12b0139` |
| +b | u8 | 保持零 | 前述全包清零 |
| +c | u32 | 输入 +4 的 u32，详细语义尚未证明 | `34f2fd4 a14f00b9` |

录像开始调用点得到的 wire 示例为
`0d 20 2b 03 10 00 01 80 01 00 05 00 01 00 00 00`。
这只是该静态调用点的参数推导，不是本次运行抓到的请求。

## 同步/异步分支

输入 `+8:u8` 在 `0x34f2fd0` 读取，在 `0x34f2fe0` 为零时跳向异步路径。
这个字段决定 AP 调用方式；不额外出现在 wire 中。

- 非零分支：`0x34f2fec e0e88052` / `0x34f2ff8 8050b272`
  组合 SID `0x92840747`，w2=`0x10`、w4=`0x0c`，
  `0x34f3004 4ac9ff97` 调 `0x34e552c`，随后把返回状态经 `0x34e349c`
  转换后写入调用者的结果 word。
- 零分支：在锁保护下把 `0x910fa24` 计数加一，再于 `0x34f3054`
  调 `0x34e521c(D,16)`，不等同步完成回复。

后续main按原 `.rela.plt` 与PLT/GOT核对了 `0x34e521c` 的直接发送路径，
不存在已证的额外AP后台音频队列线程依赖：

| 调用点 | PLT / GOT | 原符号与作用 |
|---|---|---|
| `34e5254` | `1660060 / 5bc2838` | `osal_valloc_msg_wait`，owner92840747，按输入长度分配 |
| `34e5388` | `165d3e0 / 5bc11f8` | `memcpy`，复制原请求 |
| `34e5398` | `165d600 / 5bc1308` | `osal_set_msg_src`，source来自全局910fa20 |
| `34e53a8` | `165ead0 / 5bc1d70` | `osal_snd_msg`，发送至92840747 |

目的服务对032b的消费、计数的归零/完成时机仍未闭合；异步发送返回也不证明播放。

## 实现边界与下一步

真实原 AP 提示音入口已经找到的是 `032b`，不能把“没有 0203”作为 AP 不会发提示音的证明。
当前模型仍明确拒绝 `032b`；这份静态合同不足以把拒绝改成成功 ACK。

下一步应核对 `032b` 在现有 run 中是否实际出现，并跟踪目的服务消费者；
原输入+0的编号域尚未闭合：RECSTART/RECSTOP的BeepID与KindID恰好都为5/6，
只凭这两个调用点不能普遍命名为BeepID。索引中的STARTUP则是BeepID0、KindID0x14，
上游调用可能已经转换，因此不能再次盲目转换或直接按错误的列取资源。
需要从消费侧证明该编号→资源/KindID的映射、循环参数、停止及完成/归还时机。
对接 WAV 或宿主设备前，还需证明采样率与通道配置，不能把导出工具的 48kHz 假设当合同。

本目录下 `audio-playback-ap/verify.py` 可独立只读复核样本身份、四条直接 BL、
RECSTART/RECSTOP 的 ADRP+ADD 及原日志文本：

```sh
python3 report/audio-playback-ap/verify.py --ap runtime/analysis/menu-root/usr/lib/appFw.so
```

输出的 `verified` 只指静态调用链；`playback_verified` 与 `host_audio_verified` 保持 false。
完整带字节反汇编研究中间证据暂存于 `scratch/cp-audio/`：
`ap_sound_emitters.py`、`ap-sound-emitters.txt`、`ap-start-sound-wrapper.txt`、
`ap-start-sound-body.txt`、`ap-sound-callers.txt`。这些是研究中间件；核心已证结论的复核
不依赖该 scratch 目录。

## CP转发局部合同（转换表已核，入口和完成仍待补证）

独立代理定位 `1c4944:05f0f8fe → bl 1ca738`，main已核该单条Thumb调用和构造器原字节。
`1ca738` 的输出为sp+8的16B消息：
`1ca74a/74e/752` 写2004/0203头，`1ca754/756/75a` 写长度10、flags1；
`1ca746:cde90400` 清零payload。

| 输入/输出同偏移 | 宽度 | 原日志命名 | main已核转发指令 |
|---|---:|---|---|
| +8 | u8 | request | `1ca75c:2c7a` / `1ca782:8df81040` |
| +9 | u8 | reserve | `1ca786:6b7a` / `1ca7ba:8df81190` |
| +a | u8 | kind | `1ca7ce:ae7a` / `1ca7d4:8df81260` |
| +c | u32 | loop | `1ca7d8:ed68` / `1ca7da:0595` |

输入+b不读，输出+b保持零。request>=3或reserve不在0/1时记录错误日志后仍转发原值，
不能将这些日志检查写成已证的严格拒绝规则。relay内没有编号转换或loop算术变换。
这支持称+a为原日志的kind，但仍未闭合它在ADF查表时的完整编号域，亦未证明loop单位。

`1ca856..1ca868` 构造r0=9058003f、r1=消息、r2=16、r3=928407b9，调6ae3f8。
r3参数角色尚未核实，不得写成AP原服务92840747或自动当成已证reply owner。
即时发送返回0不能证明音频消费或播放结束。

尚需补：转换器的实际入口参数与队列接收/框架分派条件；ADF0203对象分派与注册表查找；
原应答、播放完成、原消息释放和AP waiter归还的先后。
`AdfSystemSoundRequestBase/Biz/Pin/TextSpeech`及67f24e、6809ce为定向线索，未作实现合同。
相关研究窗口在 `scratch/cp-audio-032b/`；播放拒绝继续保留。

## CP wire 032b → 内部 event c3：两张表的静态映射

新的同题独立调查 A/B 均已交付结束。B 完成 wire 转换表；A 独立找到同一 c3 写入候选和内部条件路径，但明确未闭合 wire 边，不能写成两份都完成。主会话完整读取两份报告，执行 B 的断言，再用独立原字节读取、TBH 位移运算与 BL 解码核查以下链。CP 样本大小 18090880 B、SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`；以下地址是 CPVA，RAW=CPVA−0x108000，明确代码窗口按 Thumb 解码，跳表按数据读取。

| 原指令或表项 | 原字节 / 计算 | 已证含义 |
| --- | --- | --- |
| `1c5326` | `6388`，`ldrh r3,[r4,#2]` | 读取 wire command，而非 payload kind |
| `1c533a`、`1c5344` | `a3f54070` 减 0x300；`dfe810f0` TBH | wire032b 对应索引2b，表基址1c5348 |
| `1c539e` | `6301`，LE半字0163 | `1c5348+2×0163=1c560e` |
| `1c560e/1c5610` | `c320 0790` | 写内部 event c3 到 sp+1c |
| `1c4012`、`1c415c` | TBH基址1c4016，`9604` | eventc3−20=a3；`1c4016+2×0496=1c4942` |
| `1c4944` | `05f0f8fe` | 原 BL 指向1ca738，即前述0203 relay |

相邻 wire032a 和032c 分别经 `1c539c:6001`、`1c53a0:6601` 到1c5608/1c5614，写 eventc2/c4；不推广成全局编号线性公式，也不从 event 编号推出声音资源编号域。

转换器信封 F=sp+18，event在F+4，原请求指针在F+10。`1c530a:9846` 保存入口r3；`1c59e2:b8f1010f` 比较它是否为1，`1c59ea:08bf / 1c59ec:0a94` 仅相等才把原消息写入F+10。因此 **实际入口r3==1、消息队列92840748的接收和原框架通过条件尚未闭合**，不能把两个表的正确映射扩成整条服务必然运行可达。

A 另指出内部表 `d16d04`。main 核 `1c322e:0888` 读取内部信封事件、`1c3244:5529` 比较索引与 `0x55`，因此首表实际是 **85 个 u32**；`d16de0:c3000000` 位于十进制索引 **55（0x37）**，不是十进制 37，也不是总共 55 项。这证明 c3 在该内部 `through event req` 表中；不证明 wire 校验、实际对象状态或调度框架必然通过。虚表 +14/+18 由另一谓词结果选择，仍须核实际入口与对象，不能把表成员资格当运行消费证据。

### main 有界补核：已定位转换器的两个直接调用分支

main 在 CPVA `1b0000..1e0000` 范围仅扫描 Thumb BL 位型，再核调用窗口，找到 `1bef46` 与 `1beffc` 两个到 `1c5300` 的直接调用。对应原循环函数入口 `1bee34`；`1bee3e..1bee44` 组合 r4=`92840747`，`1bee48..1bee50` 用 r0=r4、r1=sp+c、r2=-1 调 `5653a8`，成功支路从 sp+c 取 M。底层 API 名称和实际收包本轮未核，不能把该调用直接记成动态接收通过。

`1bee94` 调 `bec28e(M)`；后者原指令 `bec290:50f8080c` 读取 M−8 的 u32，随后低8位作为局部类别 switch。其含义不能混同 wire 的 request+8 字段；若干特殊 source 还有前置分支，不能忽略：

- 类别8：表基址 `1bef06`、表项 `1bef16:7700` → `1beff4`；`0398 5146 0022 0123` 设置 r0=M、r1=sl、r2=0、r3=1，再调用转换器。这个静态分支满足保留 M 的条件。
- 类别1：表项 `1bef08:1c00` → `1bef3e`；相同参数但 `r3=0`，转换器不保留 M，不能把它当同一种播放请求路径。

因此入口缺口已从“完全找不到 caller”缩为“实际到达92840747的 AP 请求在分配元数据/前置分支上属于什么类别，以及后续92840748框架如何接收”。类别8的分支真实存在，不证明本次请求实际走了它。main 原字节断言在 `scratch/main-audio-entry/verify.py` 实际通过，核心字节与两个 caller 表项也加入下述公开复核器；实际类别、运行收包和播放仍 false。

主会话交付一个不依赖 scratch、仅使用标准库的只读复核器：

```bash
python3 report/audio-playback-cp/verify.py --cp runtime/analysis/menu-root/cp/cpapp-b.bin
```

已实际执行通过；输出 `static_mapping_verified=true`，入口参数、队列接收、完成合同、播放与宿主声音均 false。B 最初因轮次结束未执行其脚本，主会话已补做实际验证，不能把它描述为代理当时已验证。运行实现继续拒绝尚未闭合的播放请求，不添加猜测 ACK。

## ADF 下一局部：记录查找与 Biz 控制结构（入口未闭合）

任务52下一轮双人独立调查中，A/B均部分交付并结束，均未保存报告；main重新核原CP字节并补两个目录的MAIN记录。A的round3未执行，不算取证。这里不是原0203消费者已经运行的证据。

`6809ce` 从对象+14开始扫描30项、步长28；有效标志byte+2须为1，kind取byte+0与输入比较；未命中返回e002。命中后复制记录到调用者结果，并保存其另一个word到结果+20。对象/注册写入来源仍未证。

`67f2d6`（原Thumb虚表指针d14aa4=67f2d7）读取其payload+2作为kind，调用上述查表；命中后令W=结果+8、A=结果+20，构造目标字段+c=A、+10=W+40、+14=A、+18=W+A。payload+4原word保存到目标+20，没有局部单位换算证据。不能仅按这些加法命名为PCM起点/长度。

后续main定长原指令补核注册端：`6807fe`返回O=01230770；`680808`的一条分支经比较器`680942`调用`19ccbc`，后者在O+16起找有效byte为0的30个空槽，stride28，向槽首Q=O+8+28*i复制候选32B。它再读候选+0的64位值，用ceedb0的四个区域记录做地址范围映射，把换算结果写Q+20。故A确实来自地址转换，前一阶段将结果+20假称“长度”的解释撤回；W仍是候选原第三word，其构造/格式语义未闭合。680942本身仅比较并返回分类码，不能误称写入者。主会话原字节和代理局部证据分开保留。

这只支持有限字段构造，不闭合9058003f/2004/0203到该虚方法的选择、注册buffer同源、格式/长度头部语义、loop单位、实际消费、owner或完成/归还。`playback_verified`仍false，不从“有注册表”升级为“可以播放”。

成果内 `report/audio-playback-adf/verify.py --cp runtime/analysis/menu-root/cp/cpapp-b.bin` 已由main实际运行通过，核原对象地址、30槽查询、空槽注册复制、地址结果写入及静态虚表引用；输出只有局部静态结构true，wire0203分派/格式/loop/ownership/播放全部false。它不执行CP代码，也不提供声音实现或猜测应答。

## tap点结论与最小宿主路径（main已核代理取证，本轮）

代理（deepseek）取证`scratch/audio-host-path-deepseek/`（REPORT.md+verify.py），main独立复核原字节与源文件：结构声明**成立**。结论：**存在定义明确的tap点**——CP收到`0x200d/0x032b`播放请求后，按kind查0329已注册切片（`audio_phys64=0x81d000000`+`size`，即`SysSound.bin[offset:offset+size)`原字节）处取数交宿主消费者，即可得到原厂资产字节（混音前）。但原固件最终汇点（ADF混音器→AudioIpIf/I2S DAC）未建模，**混音后帧（含032c音量/032a路由作用）当前不可tap**，只能tap混音前原始资产切片。

main已核：`audio-device.c:53-66`确对0203/032b直接`reject playback-not-supported`；`pcm_sink_open/write/close`在guest侧**无任何调用者**；0329只校`in[23]/in[24]`，`+13`（Priority）确实从未被使用。0329描述符布局实测（phys64@+0、size@+8、kind@+12、priority=6@+13、regist@+14），beeplist 71行解析通过，`SysSound.bin` 0x10340，无前导128B（beep-extract.py的128B前导假设**错误**，样值流在偏移0即开始）。

修正代理报告的不精确偏移（字符串均存在，偏移以实测为准）：`SetLpcmWritePath`@0xecbf9f、`SET_OUTPUT Execute`@0xe2ffbe（i2s_48k@0xe2ffd8）、`arg1:OutType`@0xe34a8e、`Sysnd Mem Area`@0xe36797（LPCM Buffer PB Start@0xe367ac）。verify.py 18/23过，5个FAIL全是脚本硬编码字符串偏移差几字节，非结构错误。

最小诚实路径：audio-device.c实现0203/032b取数（kind→已注册slot→从full_sound_ready()校验过的backing取[offset,offset+size)原字节）→交宿主pcm-sink；采样率/位宽先作**标注假设**（16bit/48k，来自I2S格式表首项，非wire证据），ACK只在取数+交付成功后发。仍不实现032a/032c到PCM的混音作用（未闭合）。`playback_verified`/`audio_output_verified`仍false——本结论只确立tap点，不冒充播放已通。
