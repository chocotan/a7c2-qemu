# REC「存储卡无空间」容量/可记录前 frontier（Task #50）

状态：**未闭合**。已确定“哪条规则在说这句话、它读了哪些原字段”，尚未确定“空间不足”这个
判定的真实来源。全程只读观察，没有写入容量、剩余张数、ready、选槽，也没有清错或空 ACK。

## 最新观测层纠正：旧named状态读的是+08基值

main进一步核原getter/ROM初始化链，发现此前把5584c38表+08等同实时值的角色判断错误。102d/102e的+08 cell为7e83b28/7e83b48，ROM基值初始化本就写0/30；通用模型读/写/通知配对中的28bb0c8走+20，读取7e83b10/7e83b30。其他12个named媒体观测也要逐个分层，1052不是简单固定减偏移。原日志没有修改，但“高层实时media/recordable未更新、仍0/30”的推断撤回；不能仅凭旧08读数断言状态传播缺失。

原LCD无空间、实际selector223、原谓词直接读取字段、Fsys空闲结构及文件真实读写/热插拔是独立证据，保持各自范围。Task67结束后main才修改collector：08保留`_base08`，20作为值访问器，结果及事件标记revision2，42tests实际通过。Task70新标准128MiB只读采样正在正常admission下运行，不使用旧force-reaper。真正实时状态与生产者仍待这个新样本，旧readonly采样准确读到了地址不等于语义已证明。详见media-producer-frontier/原指令复核器和两层地址计划。

还有一层更根本的限制：名字目录`57f99a0+id*8`给`0x1037..0x103c`的名字是`PRM_HAITA_..._relay_...`这类自动拼接依赖名，而同一批键的validator范围都是`(-15,15,1)`有符号数值；`0x1052`同样如此却名为“剩余容量”。也就是说**名字目录编号与本分发表/校验器键空间的同一性整体未证**，至少在`0x10xx`段存在实证冲突。因此本collector里所有`prm_*`标签只能算“目录派生标签”，不是已证的属性语义；`09e1/0a13/102d/102e/138e`的语义同样未经独立动态确认，不得据名字断言“挂载/可录/容量”。

另有一条独立静态反证：分发表键`0x1052`（原`prm_1052_remaining_capacity_slot1`）的setter受`(-15,15,1)`有符号范围校验，运行期由`0x2506ff0(0x103c)`转接，`0x2624298`为`set_picture_profile_black_level`。名字目录序号与分发表键的同一性未证明，故该字段已从媒体表移出，改为只读的`dispatch_1052_unresolved_*`；原"剩余容量字段=0"的说法撤回。容量消费者仍未知，不能用该零值解释提示。

后续修正采样`run-6frwm5f2`现已完成：64对原REC selector里值层102d/e确实0/30（同时基值也0/30），其他10字段均0；62次223/2次ffff，LCD仍无空间。该新样本仅建立本次REC时刻的数值，仍未证明零值enum、写入历史或实时生产者，不能直接把0叫未挂载/不可录。main核revision2每事件、32块guest/QMP、完整128MiB卡SHA `f4bc982aae5ec7d7a986d6e2109173c7cff313f0933ab13ca818a78f04c534ae`、fsck0、原Flush/owner和CPU恢复、source未变及正常关闭，capture=false。旧日志没有修改，旧推断仍撤回。

## 有效1GiB对照已完成

`run-lptxo5re`的逻辑1GiB sparse-file在guest启动原bootin前完整SHA与原输入cb597447...6dde一致，真实RM接受1GiB，原Fsys空闲64917/65518个16KiB cluster（约1014.33MiB），完整导出256×4MiB原guest/QMP摘要均一致，卡SHA `468ecc45a007f9a9bd8a1f082d732e5d18427efe0b718e31c9936a7867d5114f`、独立fsck0/601clusters used、原Flush/owner恢复及CPU运行通过。main独立再算原输入仍同cb597447...6dde。

实际LCD仍无空间，64对原selector中62次223、2次ffff，无未配对/cleanup错误。本案例只说明这组更大合法FAT16输入没有解除拒绝；不是所有容量/格式/配置均无关，也不是单因素容量因果试验（交付编码/簇大小等与128MiB参照不同）。旧08字段只按基值存档，capture=false。此前格式preflight/OOM/dd准备失败仍保留且不作容量反证。

## 最新生产者调查纠正：原“apply”其实是设置值校验

本轮A/B均已结束并分别落盘，main独立核原指令后确认：2e2232c在input+b60/b64读取值并传102d/102e给28bbcc8；后者用56c4118的24B谓词表检查范围/枚举，相关379d字节是按propertyID索引的状态表，不是input长度。该恢复/导入链不能当作实时媒体值发布者。旧“write-table”“stub返回1所以不能写”的推断撤回。实际mode输入stride为2074，两个序列化键是02cf0f05/02cf0b91；键不是CP消息ID。

main已核真正dispatch表的setter及shadow/current差别，详见`media-producer-frontier/`及实际运行通过的只读verify。公开seed中同编码Backup条目也为0/30，但没有据相等认定当前run读取了它。实际写入调用栈、shadow→current提交者和媒体消息来源仍未闭合。

原Fsys的124MiB实际空闲与文件读写已证，不能继续说“返回空闲为零”；这也不穷尽上层录像的最小容量/格式条件。Task67正在做新的真实输入案例：1GiB FAT16镜像，经BPB/fsck验证，仍走同一个RM2和原Fsys计算容量，不修改任何cap/remaining/ready。案例未返回前不猜它会解除门槛；即使无变化，也只否定该案例足以解除，不能全局宣布所有容量/格式无关。

## 最新对照：RM通道修复没有解除REC规则

修正RM opcode9 rec+4为默认R1对应mask2后，原SD通知、三轮Unmount/Mount、重插后的完整DB/XML消费及显式原Fsys写入诊断已分别通过（见sd-hotplug-progress.md）。main随后单独重跑原REC规则，不从这些存储成功推出可录像。

实际 `run-e_mnhlul` 的原136B配置回复record1+4确为2，启动身份不是旧mask1。原选择器64次返回中仍有61次index223、3次ffff，记录5905988/predicate187f130及两条消息ID不变。main直接打开本轮原LCD，仍显示“存储卡无空间。”。所选entry的实际字段：still_live0/movie_live1；PRM09e1/09e4媒体状态0/0、PRM0a13/0a17文件系统状态0/0、movie_recordable102d/102e=0/30、remaining1052=0、recordable138e=0、原recording-media两setting=0/0。旧observer的mount_1=2/mount_2=0标签保留原日志，不能据旧标签替代上述严格命名的PRM字段。

这将缺口继续限定在高层媒体/可录制状态来源与传播，不把本轮无变化说成mask修复失败，也不把存储卡真的耗尽当事实。规则描述的“插槽1无空间”仅是提示分类，本身不证明上层已正确接收单物理卡映射。单槽硬件事实不变。

本轮只读GDB有64个完整entry/return、unreturned0，清理无错误，独立QMP/串口确认CPU运行；原关闭正常Flush/导出/resume。整卡main独立SHA `38070d187e6cf1ccd201150bd1cbf8a4d3fb4cc30ac483f06f12a90afd36849e` 与export相同，独立fsck0、11files/4732of65399clusters。`main-post-mask-rec-review.json` 保留具体entry和原record，录制/拍摄/根因闭合均false。下一项应是可记录状态原生产者/消息消费者，不再无差别重跑此规则，也不强写remaining/recordable值。

## 1. 实际选中的规则就是这句话

`run-neprf92x`（`--media-policy`）在真实 REC 后，原选择器 64 次返回中 **61 次为 `0x223`**，
其余 3 次为 `0xffff`（无记录）。该记录：

| 项 | 值 |
|---|---|
| record VA | `0x5905988`（index `0x223`，stride `0xa0`） |
| predicate | `0x187f130` |
| primary 消息 | `0x0200a1b4` |
| alternate 消息 | `0x0200a04a` |

两条消息在 `string_simplifiedchinese_horizontal.uxc`（SHA `f136388b…`）中：

| key | 偏移 | header | 文本 |
|---|---|---|---|
| `0x0200a1b4` | `0x57c8` | `0x1e00a1b4` | `存储卡无空间。\n插槽1` |
| `0x0200a1b5` | `0x57ec` | `0x1e00a1b5` | `存储卡无空间。\n插槽2` |
| `0x0200a04a` | `0x1c24` | `0x1e00a04a` | `存储卡无空间。` |

⇒ 原固件选中的是**「插槽1无空间」的提示类别**，不是「无卡」文本；这不单凭提示证明
物理卡状态或真实剩余容量。此前把同一句提示当作“无卡/选槽”问题的延伸不准确；
误写选槽问题（`KEY_GATE_OVERRIDE`）已单独修复。

## 2. 谓词 `0x187f130` 的实际分支

272 B，SHA `2bfdc981f29a5673cb4dd11db009416309b0f9e4e8146349d95ae78a21921b85`。按测得值
（`0x7e811b0=1`、`0x7e6e810=1`、`0x7e6e7f0=0`、`0x7e73770=0`）代入，命中路径为：

```
0x187f170  if (G_2878cc8==1 || G_2879038==2 || G_2878ef8==1)  -> 0x187f1a0
0x187f1a0  if (G_2867694==0) return 1                        ; 实测=1，继续
0x187f1ac  if (G_286766c!=0) { ==2 -> 0x187f1b8 else return 0 }; 实测=0，继续
0x187f1b8  if (G_286cfc8==0) return 1   <-- 命中            ; 实测=0
```

即：触摸拍摄功能门槛通过 → 该字段非零 → 另一个字段为零 → `PRM_setting_release_wo_card`
为 Disable → 规则成立。**规则本身没有做任何空间计算**，因此“无空间”是从上游可记录状态里
取来的结论，而不是这条规则算出来的。

## 3. 字段真名（dispatch id → 名字数组 `0x57f99a0`）

用 `scratch/capacity-main/resolve_getters.py` 把每个 getter 解成字段 VA、再用属性派发表
（`0x5584c38`，stride `0x30`，成员指针在 `+0x18`）取 id，再查名字数组：

| getter | 字段 | id | 名字 |
|---|---|---|---|
| `0x2878cc8` | `0x7e811b0` | `0xef0` | `PRM_HAITA_system_mode_setting_shooting_touch_function` |
| `0x2879038` | `0x7e81470` | `0xf06` | `PRM_setting_focus_position_during_touch_operation` |
| `0x2878ef8` | `0x7e81370` | `0xefe` | `PRM_HAITA_breathing_correction_lens_type_lens_information` |
| `0x286cfc8` | `0x7e73770` | `0x804` | `PRM_setting_release_wo_card` |
| `0x2879804` | `0x7e81af0` | `0xf38` | `PRM_still_temperature_level` |
| `0x288badc` | `0x7eddbc8` | `0x1bf4` | `VAL_license_state_LICENSE_STATE_CONFIRMED` |
| `0x286ae5c` | `0x7e71a70` | `0x705` | `_INFRA_PIN_ATOM(IMAGING, RAW, OUT, 0)` |
| `0x286af4c` | `0x7e71b50` | `0x70b` | `_INFRA_PIN_ATOM(INFRABB, RAW, OUT, 0)` |
| `0x2867644` | `0x7e6e7c8` | `0x59e` | 名字运行时填（见 §5） |
| `0x286766c` | `0x7e6e7f0` | `0x59f` | 同上 |
| `0x2867694` | `0x7e6e810` | `0x5a0` | 同上 |

名字数组本身也验证过：id `0x802` → `PRM_setting_release_wo_lens`、`0x804` →
`PRM_setting_release_wo_card`，所以“`0x804` 是 `release_wo_card`”不是单点推断。

## 4. 纠正：早先那 8 个“容量字段”多是误选

上一轮为容量观察加入的 8 个 getter 里，多数其实与该谓词无关
（`PRM_HAITA_hdmi_connect_state_…`、`PRM_face_af_mode_face_cursor_status`、
`PRM_setting_face_priority_in_af`、`PRM_HAITA_…movie_rec_frame_rate…`）。真正被
`0x187f130` 早期门槛读取的只有 `0xef0/0xf06/0xefe` 三项。已把观察集合**替换**为谓词真实读取
的字段（不是改名），并保留“容量/满/时长语义未证明”的警示注释。
宿主回归：`test_media_predicate_watch.py` + `test_request_queue_watch.py` **39 passed**，
其中一项直接从原字节解码 `ADRP+ADD+ADD+ADD+RET` 断言 8 个 getter 的绑定地址。

## 5. `0x59e/0x59f/0x5a0/0x5c1` 的语义仍未定

这四个槽在名字数组里是**运行时填充**（单元格持有 `0x9115c60`/`0x9111908` 这类未重定位占位），
所以“静态无名字”不能推出“无生产者”。它们同属一个生成式 apply 块：结构体
`+0x5b8…+0x5e0` 依次映射到属性 `0x594…0x5a0`（跳过 `0x598/0x59d`），apply 函数入口
`0x2e2232c`，两个调用者 `0x2e2e3c8` 与 `0x2f559c0`；结构体是**调用方传入**的
（`0x379d` 字节快照，调用方本地缓冲只作错误上下文）。

## 6. 有界否定（写在报告里，避免重复挖）

按“精确偏移 `str`”扫 `+0x5d8/+0x5dc/+0x5e0` 得到 175/25/165 个候选，其中看起来最像的连续三条
`0x1b5c810 / 0x1b5c8c4 / 0x1b5c8d0` 实际是**资源 ID 表初始化**（周围全是 `0x02002xxx`
常量）。⇒ 单纯按结构体偏移匹配无法区分对象身份，**这不能当作“找到生产者”，也不能当作
“不存在生产者”**。真正的生产者仍待按对象身份或动态观察确定。

## 7. 容量数值通道：之前的 trace 不足以判定

`Fsys_GetFreeSpace` 的 wrapper 原来只记录输出结构**首 word**（`0xff77`），而原调用方
的算术用的是 `out+0xc`、`out+0x10`、`out+0x14`、`out+0x18`、`out+0x1c`
（`libInfraFsys` 导出 `0x34de0`，480 B，SHA `594bf28e…`）。所以“首 word=0xff77”
既不能称“空闲值”，也不能称“空间为 0”。现已改为记录该结构 **8 个 word**，宿主回归
`test_fsys_unmount_trace.py`+`test_fsys_flush_barrier.py` **2 passed / 24 subtests**；
本轮真实运行的数值待取。

同一次运行里 `GetFreeSpace` 只被调用 6 次，全部 `result=0`；Fsys 侧其它 op 也只有
`Mkdir/Seek/Open/WriteAndFlush/Mount` 少量几次。也就是说：**REC 被拒之前，固件几乎没向
文件层问过空间**——这一点本身支持“无空间”来自别处的状态（消息/快照），而不是本次实时计算。

## 8. 不声明

- 没有证明 `0x59e/0x59f/0x5a0` 的语义，也没有证明它们由谁写成 0。
- 没有获得原固件的照片或视频；`capture_verified` 保持 `false`。
- 没有用写容量、写剩余数、写 ready、清错或空 ACK 的方式消除提示。

## 9. 纠正记录：派发表段映射（本轮自查，重要）

原 AP 的派发表 `0x5584c38` 位于**第二个 PT_LOAD 段**，该段满足
**VA = 文件偏移 + 0x10000**（段表：`(vaddr 0x51b7718, off 0x51a7718, filesz 0xdac8a0)`）。
直接用“文件偏移 = VA”去读行会读到无关字节。我自己两次踩了这个坑：

- 第一次得到一个快速脚本给出的 `PRM_*` 状态地址（`0x7e50638`、`0x7ead84c`、`0x7e83b10` 等），
  **全部作废**；`STATUS.md` 与本文早期段落中的这些值不再成立。
- 第二次更糟：修正脚本里写死的行偏移仍是裸文件偏移，于是“测试”与“字典”用同一份错字节
  互相验证成了闭环。现在测试改为**自行解析 ELF64 段表**（`_load_segments`/`_va_to_offset`），
  从原字节取行的 getter 再解出目标地址比对，闭环被打破。

行布局（用正确映射读出的真实结构）：

| 列 | 含义 |
|---|---|
| `+0x00` | supported 谓词（`mov w0,#1` 或 `#0`） |
| `+0x08` | **getter**（`adrp x0` … `ldr w0`）→ 运行时真值所在 |
| `+0x10` | setter（写影子单元之一） |
| `+0x18` | setter（`resolve_getters.py` 原先按此列取字段） |

按 `+0x08` getter 得到的**最终字段地址**：

| 属性 | id | 字段 |
|---|---|---|
| `PRM_media_movie_recordable_state_slot1` | `0x102d` | `0x7e83b28` |
| `PRM_media_movie_recordable_state_slot2` | `0x102e` | `0x7e83b48` |
| `PRM_media_mount_state_slot1` | `0x9e1` | `0x7e78900` |
| `PRM_media_mount_state_slot2` | `0x9e4` | `0x7e78960` |
| `PRM_media_filesystem_mount_state_slot1` | `0xa13` | `0x7e78f40` |
| `PRM_media_filesystem_mount_state_slot2` | `0xa17` | `0x7e78fc0` |
| `PRM_media_remaining_capacity_of_memory_for_create_new_folder_slot1` | `0x1052` | `0x7e84078` |
| `PRM_media_recordable_state_movie_slot1` | `0x138e` | `0x7e8a268` |
| `PRM_media_full_state_still_slot1` | `0x9f5` | `0x7e78b80` |
| `PRM_media_full_state_movie_slot1` | `0xa18` | `0x7e78fe0` |

宿主测试 `test_media_state_fields_follow_original_dispatch_getters` 逐条从原字节核验上表；
`test_media_predicate_watch.py` **13 passed**，与请求队列测试合计 **40 passed**。

### 9.1 由此撤回的旧标注

旧媒体证据里把 `0x7e80dd0` / `0x7e80df0` 当作“`mount_1`/`mount_2`（已挂载/未挂载）”。
按正确映射，这两个地址属于属性 `0xed1` / `0xed2`：

```
0xed1 PRM_HAITA_setting_rec_media_during_hdmi_output_exposure_mode
0xed2 PRM_HAITA_setting_rec_media_during_hdmi_output_...setting_file_format
```

即**HDMI 输出期间的录制媒体抑制位**，不是挂载状态。因此此前“`mount1=2` 表示已挂载”
一类推断**不成立**，涉及它们的结论需重做。真正的挂载状态是上表的
`PRM_media_mount_state_slot1/slot2` 与 `PRM_media_filesystem_mount_state_slot1/slot2`。

## 10. 容量数值已排除（本轮新证据）

`Fsys_GetFreeSpace` 整段结构（8 word）在真实 REC 运行中为：

```
REC 前:      ff77 ff77 fe00 fe00 0 0 200 4
写卡之后:    ff77 ecfb ec00 ec00 0 0 200 4
```

`0xff77 = 65399`（卡总簇数）、`0xecfb = 60667`（= 65399 − 4732，空闲簇数）、
`0x200 × 4 = 2048` 正是簇大小。即原 Fsys 报告的空闲量约 **124–127 MiB**，与独立
`fsck` 结果一致。⇒ **“无空间”不是数值算错**，而是可记录状态没建立起来；
先前“首 word 0xff77 是空闲值/空间为 0”的说法作废（首 word 是总簇数）。

## 11. 真实媒体状态实测（run-kik3dw9s）

按第 9 节修正后的地址，在真实 REC 运行里读出（规则求值瞬间，64 次返回中 61 次仍为 `0x223`）：

| 单元 | 值 |
|---|---|
| `PRM_media_mount_state_slot1` / `slot2` | `0` / `0` |
| `PRM_media_filesystem_mount_state_slot1` / `slot2` | `0` / `0` |
| `PRM_media_movie_recordable_state_slot1` / `slot2` | **`0`** / **`30`** |
| `PRM_media_remaining_capacity_of_memory_for_create_new_folder_slot1` | `0` |
| `PRM_media_recordable_state_movie_slot1` | `0` |
| `PRM_media_full_state_still_slot1` / `movie_slot1` | `0` / `0` |

要点：

1. **slot1 全部为 0，slot2 的 `movie_recordable_state` 有真实值 30**。即固件把我们的虚拟卡
   放在**逻辑 RM2/slot2**，而录制媒体选择针对的是 **slot1**（注释消息也是“插槽1”变体）。
2. 这与“A7C II 只有一个物理卡槽”的前提不矛盾：物理只有一个槽，内部逻辑编号如何分配是
   设备拓扑问题。此前把“卡在”等同于“slot1 有卡”是不成立的。
3. 因此“存储卡无空间”更可能是**媒体在另一逻辑槽**导致的可记录状态缺失，而不是容量数值问题
   （容量数值已在第 10 节用真实结构排除）。

## 12. 单槽映射开关（候选，默认行为不变）

为验证第 11 节的解释，新增一个**显式开关**，把唯一的虚拟卡报告在逻辑 RM1/slot1：

- `rm-file-device.c`：opcode 9 回复的媒体字段写在 `state.slot` 指定的记录上
  （`MENU_RM_FILE_SLOT=0` → 记录 0 / RM1；默认 1 → 记录 1 / RM2，与原行为一致；
  非法值一律 `native_rm_file_start` 失败）。
- 只有一条记录携带媒体字段，另一条保持空，避免“两张卡”的伪拓扑。
- 宿主测试新增 `slot0` / `slotbad` 场景（ASan+UBSan），`test_rm_file_device.py`
  **14 subtests 全过**；launcher/manifest 记录 profile `virtual-rm1-mmc-file-v1`。
- 该开关**只改设备拓扑声明**，不写容量、剩余数、ready、选槽状态，也不清除任何错误。

结果待真实运行验证：若 slot1 状态被填上且提示消失，则说明这是正确映射；
若不是，则收回这一解释并记录否定结果。

## 13. 单槽映射开关：第一次实验**无效**（开关未生效，作废）

> 后续自查：`start-menu.profile_environment()` 会剥离全部 `MENU_*` 变量，因此该次运行的
> `MENU_RM_SLOT1` 从未到达 guest，manifest 仍记录 `virtual-rm2-mmc-file-v1`，控制台也没有
> `export MENU_RM_FILE_SLOT=0`。所以下面的“否定”**不是**对映射假设的否定，而是无效实验；
> 已补上透传（`start-menu.py` 显式转发 `MENU_RM_SLOT1=1`，并有回归用例）。原文保留以便追溯。

### 13.1（作废的）第一次结果：**否定**

`run-yrww46eb`（`--media-policy-slot1`，profile `virtual-rm1-mmc-file-v1`）的实际结果：

| 判据 | 结果 |
|---|---|
| 挂载目标 | 仍为 `OBS FULL_MEDIA_MOUNT_DEVICE_OPEN_ENTER path=/nondev/rm2`、`FSYS_FILE_TRACE op=Mount path=/nondev/rm2` |
| `movie_recordable_state_slot1` / `slot2` | `0` / `30`（与改前一致） |
| `media_mount_state_slot1/2`、`filesystem_mount_state_slot1/2` | 全 `0` |
| REC 规则 | 64 次返回中 62 次仍为 `0x223` |
| SD 导出 | `ok=true`、`fsck_rc=0`、`flush=resumed`、SHA `36332eee…` |

⇒ **把媒体字段改到 RM 表记录 0 并不会改变固件选择的逻辑 RM**。`/nondev/rm2` 来自固件自身的
配置/拓扑决策，而不是我们那条记录的位置。因此：

- 不能声称“单槽映射已修复”；`bc027048c` 的探索**失败并已记录**。
- 反过来说明这台机器的**单一物理槽在固件内部就是 rm2/slot2**；“slot1 全 0”是固件拓扑的
  必然结果，不是我们少挂了一张卡。
- 该开关保留为**诊断选项**（默认关闭、行为与原版一致），不用于冒充修复。

## 14. 下一步判据

既然媒体只在 slot2，而提示措辞是“插槽1”，剩下的可能收窄为：
`PRM_setting_still_recording_media` / `PRM_setting_movie_recording_media` 指向了 **slot1**
（本机不存在的槽），或可记录状态的上游另有来源。两者都用同一次运行读出（字段
`0x7e790e0` / `0x7e79450`，已加入观察集合，宿主 13 passed）。
若设置确实指向 slot1，正确做法是**经原 MENU 把录制媒体改到实际存在的槽**，而不是写状态位。

## 15. 拍摄门控实录（新工具）与地址复核

按 full 路线 `CAPTURE-INHIBIT-SOURCES.md` 的地址表，落到只读工具
`capture_gate_readback.py`（15 个单元：总禁止字节 `0x83337e3`、计数 `0x7e1c00c`、
9 个标量来源、4 个 HAITA 处理值）。设计约束：

- 分**两批**串口事务（8 + 7），最长物理行 74 字符——避免此前 26 字段回读被 BusyBox 行缓冲截断；
- 每个单元必须恰好一对 `LABEL_BEGIN`/`LABEL_RC=`，缺项或重复一律拒绝；
- `capture_verified` 恒为 `false`，本工具**只读**，不清禁止、不报 ready。

**逐条复核文档给的 getter→字段**（原字节解码，`test_capture_gate_readback.py` 已固化为回归）：

| 单元 | getter | 字段 | 结果 |
|---|---|---|---|
| USB streaming | `0x27ab3a0` | `0x7eddbc8` | ✓ |
| ee_status | `0x28623f0` | `0x7e67700` | ✓ |
| network streaming | `0x2778070` | `0x7e71a70` | ✓ |
| lens_retracted | `0x2765574` | `0x7e59cf0` | ✓ |
| focus_init_error | `0x276acc8` | `0x7e67478` | ✓ |
| zoom_init_error | `0x276ad04` | `0x7e67498` | ✓ |
| steady_error | `0x27663e8` | `0x7e5bc18` | ✓ |
| date_time | `0x2768200` | `0x7e5df40` | ✓ |
| two_slot_inhibit | `0x279cdf0` | `0x7eae2b0` | ✓ |
| release_wo_card | `0x2774194` | `0x7e6f2c8` | ✓ |

复核时踩到一个自身缺陷：我的快速校验器只处理 `adrp;add…;ldr;ret` 形式，而
`ee_status` 的 getter 是 `adrp;add…;ret`（地址直接在 `x0` 返回），于是被误判为不符。
修正后 10/10 全部一致。这条也写进测试注释，避免以后再用“只有 ldr 形式”的假设。

宿主：`test_capture_gate_readback.py` **4 passed**（命令行长度上限、单元配对、缺项/重复拒绝、
原字节 getter 复核）。运行入口 `MENU_CAPTURE_GATES=1`，默认关闭。

## 16. 拍摄门控实测（`run-81ikkv27`）：两条来源在拦，且都不是"缺镜头"

真实机身按键（半按/全按/REC）之后读出 19 个原始单元（只读；`capture_verified` 仍 false）：

| 单元 | 实测 | 文档静态阻断值 | 判定 |
|---|---|---|---|
| `CAPTURE_INHIBIT_BYTE` | **0x1** | 非零即被禁止 | 有禁止 |
| `CAPTURE_INHIBIT_COUNT` | **0x2** | — | 两个来源 |
| `GATE_EE_STATUS` | **0x0** | `0=NOT_RUNNING` | **命中：影像引擎未运行** |
| `HAITA_RELAY_TARGET` (源 0x996) | **0x5269** | `0x5269/0x526c/0x526d` | **命中：目标槽不可录/接力关闭** |
| `GATE_USB_STREAMING` | 0x0 | `1=ON` | 不拦 |
| `GATE_NETWORK_STREAMING` | 0x1 | `0=ON` | 不拦 |
| `GATE_LENS_RETRACTED` | 0x0 | `1=IN` | **不拦（镜头未缩回）** |
| `GATE_FOCUS_INIT_ERROR` | 0x1 | `0=ERROR` | **不拦（对焦初始化正常）** |
| `GATE_ZOOM_INIT_ERROR` | 0x1 | `0=ERROR` | **不拦（变焦初始化正常）** |
| `GATE_STEADY_ERROR` | 0x0 | `1=OCCURED` | 不拦 |
| `GATE_DATE_TIME` | 0x0 | `2=NOT_SET/3=UNKNOWN` | 不拦 |
| `GATE_TWO_SLOT_INHIBIT` | 0x0 | `5=NO_COMMON_FOLDER` | 不拦 |
| `HAITA_NO_LENS_RELEASE` (0xcf) | 0x1406 | `0x1408` | 不是该规则 |
| `HAITA_STEADY_SELFTIMER` (0x800) | 0x4b97 | `0x4b9a/0x4b9b` | 不是该规则 |
| `HAITA_MEDIA_TARGET` (0x8b5) | 0x4ecf | `0x4ed0/0x4ed2/0x4ed4` | 不是该规则 |
| `RELEASE_WO_LENS_LIVE` | **0x0** | 0=ENABLE | **允许无镜头释放（默认值）** |
| `RELEASE_WO_CARD_*` | 0x0 | 0=ENABLE | 允许无卡释放（默认值） |

### 结论（与用户提醒一致）

- **“缺镜头”不是拦快门的原因**：`RELEASE_WO_LENS=0(ENABLE)`、`LENS_RETRACTED=0`、
  `FOCUS_ZOOM_INIT=1(NO_ERROR)`、`HAITA_NO_LENS_RELEASE=0x1406≠0x1408`。
- 真正在拦的是**两条**，正好对应计数 2：
  1. **`ee_status = 0 (NOT_RUNNING)`** —— 影像引擎没跑起来（缺成像后端：像素源/DMA/编码）。
  2. **源 `0x996` 命中规则 ID `0x5269`** —— “保存目标/接力 + 目标槽不可录”，
     对应此前测到的 `movie_recordable_state_slot1=0`（本机唯一槽在 slot2）。
- 因此“拍照写卡”的下一步不是调镜头、也不是改槽号，而是：
  **①把影像引擎状态推进到 RUNNING（成像合同）；②让目标槽的可录状态成立（介质/可录状态合同）。**

边界：只读观测，未清禁止、未写 ready；`capture_verified=false`，仍无照片。

## 17. 两条门禁的前置条件（按已交付文档核对，避免重复劳动）

### 门禁 ①：`ee_status = 0`（影像引擎未运行）

full 路线 `IMAGING-CHAIN-CONTRACT.md` 已把这条链查到指令级，明确三点必须保留：

1. 拍照模式下 `sequence_start_ee@0x347618c` 经 `0x34761e4→0x34cb808→0x3546040`
   向 SID `0x90030001` 发 **24B、cmd 0x3003**；回复 16B，`0x35460ac` 比较 `+8 == 0xf000`。
2. **这条 16B 控制回包不能当“COMS 首帧完成/ee 已运行”，更不能预填 `f000()`**。
3. EE 置 1 的真实路径是 `0x339fc64 → 0x339fc70 → 0x338d998 → 0x338d9f4`（以及 `0x33a5af8→0x33a5b08`），
   而**触发这些置 1 的原完成事件尚未闭合**；清 0 在 `0x338e140→0x338e14c`。

⇒ 只补 3003 的请求/回复**不足以**让 `ee_status` 变 RUNNING，也不能拿它去当“引擎已运行”。
真正缺的是 **CMOS 源 SID、像素格式枚举、原分配缓冲的首帧完成与租期**——full 文档原话：
“仍缺 CMOS 源 SID、格式枚举、原分配缓冲的首帧完成与租期；禁止用 ValidState、OSD 像素或空 ACK 代替。”

### 门禁 ②：源 `0x996` 命中 `0x5269`（目标槽不可录）

同文档对该源的定义是“**保存目标限定 + 两槽 DISABLE 或接力关闭且目标槽不可录**”，
并特别说明“**接力输入是 `setting_relay_rec`（模型 `0x5a0`）**，不能简化成‘双槽未挂载’”。

实测：`0x5a0`(movie_live)=1、`movie_recordable_state_slot1=0`、`slot2=30`，
而录制媒体设置 =0（指向 slot1）。因此这条门禁的判据是**目标槽的可录状态**，
不是容量、也不是“缺卡”。

### 因此下一步是两件设备侧工作，不是继续调参

| 目标 | 需要实现 | 判定标准（不伪 ready） |
|---|---|---|
| `ee_status` → RUNNING | CMOS 像素源 + 首帧完成 + 缓冲租期（原 SSE/3003 只作为其中一步） | 原置 1 路径 `0x338d9f4` 由**真实完成事件**触发 |
| 门禁 ② 消失 | 让**目标槽**的可录状态成立（介质模型如实回答，而非写值） | 计数从 2 下降且 `0x5269` 不再选中 |

在两者完成前，`capture_verified` 保持 `false`，不得声称能拍照。

## 18. `ee_status=0` 的上游：EE 启动根本没有被发起

用运行内已有的 CP 请求观测核对（两个不同 run 一致）：

- 发往 SID `0x90030001` 的 24B 请求只有 **`0x3006` / `0x3007`**（source `0x8102…`，即已知的槽元数据）。
- **没有任何 `0x3003`**（EE 启动，source 应为 `0x80020002`）；全文 `grep 3003` = 0。

⇒ 我们并没有“发起了 EE 启动但 CP 没回”，而是**上游就没有走到 `sequence_start_ee`**。
该函数通过虚表注册（指针位于 `0x5b46790`，VA=file+0x10000 的第二段），静态无法直接取到调用者。

结合 full 文档已知的两点：
1. `0x2688ef8..0x2688f00`：**mode2 且 `ee=0` 时直接离开拍摄入口**——
   这正是我们观察到的相互卡住：ee 不运行 → 不进入拍摄 → 不发起 EE 启动。
2. 真正把 ee 置 1 的是 `0x339fc64→0x339fc70→0x338d998`（写入+通知）与 `0x33a5af8→0x33a5b08`；
   清 0 为 `0x338e140→0x338e148→0x338d998`。触发这些置 1 的完成事件仍未闭合。

### 因此成像链的下一步是**打破这个先有鸡还是先有蛋**，而不是补 3003 回包

可选的两条正当路径（都需要设备侧真实模型，不是写状态）：

- **A**：让“进入拍摄模式”这一步由真实设备事件推进（VDF/PinMem 的成像引脚数据路径完成），
  使固件自己走到 `sequence_start_ee`；再按 `IMAGING-CHAIN-CONTRACT.md` 实现 3003 的 CP 消费与 16B 回包
  （注意：该回包**不得**当作 ee 已运行）。
- **B**：先实现 CMOS 源 SID + 首帧完成 + 缓冲租期，使 `0x338d998` 的置 1 由真实完成事件触发。

两者都超出“调参/重新映射”的范围，属于成像后端实现；在此之前不宣称能拍照。
`capture_verified` 保持 `false`。

## 19. 单槽=第一个媒体：再次实验（这次开关确实生效）仍不改变挂载目标

`run-ia46v49g`（`--slot1-gates`）确认 `MENU_RM_FILE_SLOT=0` **真的进了 guest**
（控制台可见 `MENU_RM_FILE_SLOT=0`），即本轮开关**确实生效**，与之前那次无效实验不同。

结果：

| 判据 | 结果 |
|---|---|
| 挂载路径 | 仍为 `path=/nondev/rm2`（2 次） |
| 语言首设 | 失败：`Simplified Chinese font was not selected`（字体文件其实被打开过 2 次，但未落在检查窗口内） |
| 结论 | **把媒体字段放到记录 0 并不改变固件的逻辑 RM 选择** |

⇒ 逻辑 RM 名称由**固件自身的配置/路径**决定，不受我们 opcode-9 记录位置影响；
配合能力实测 `num_of_media_slot=1`，说明该机型固件把**唯一媒体实例固定叫 rm2**，
而“录制媒体”设置值为 0 指向另一个逻辑槽。这一矛盾**无法靠我们可控制的设备回答消除**：

- 改设置 = 改选槽（用户已明确禁止，且不属于“让设备如实回答”）；
- 写状态位 = 伪值（禁止）。

因此门禁②在“不改设置”的前提下**当前无正当修法**，这是一个已记录的**否定结论**，
不是尚未尝试。需要用户决策的唯一选项仍是：是否允许通过原 MENU 把录制媒体改到实际存在的槽。

另记：这次失败也说明**改变媒体声明会改变首设时序**（语言检查窗口错过字体打开），
不能把该路径当作“中性开关”使用。

## 20. 成像后端第一个可交付件：合成成像源（test pattern，明确不是传感器数据）

门禁①的根因决定了实现顺序：先要有**真实字节**进入 pin 缓冲，才谈“首帧完成/租期”，
才可能让 `ee_status` 由真实完成事件置 1。已完成第 1 步：

`runtime/analysis/device-models/cmos-source.c` + `cmos-source.h`：
- `cmos_source_init(spec)`：校验 width/height/bytes_per_pixel/stride，拒绝 stride < width*bpp，
  拒绝 >4 GiB 的帧；重配置会清零计数器。
- `cmos_source_fill(dst, capacity, frame_index)`：写入**确定性测试图案**，容量不足一律拒绝
  （`ENOSPC`）且**不写任何字节**；每帧第 0 行内嵌 `frame_index` 与该帧自身 FNV-1a 校验和，
  下游可据此证明“读到的就是这一帧”，避免陈旧缓冲冒充新帧；行内 padding 保持 0。
- `cmos_source_stats()`：只有真正写完的帧才累加 `frames/pixels/bytes`，被拒调用单独计数。
- `cmos_frame_probe()`：供消费者验证帧号与校验和。

宿主测试 `test_cmos_source.py`（ASan/UBSan）：**2 passed**。覆盖未配置即拒绝且不动缓冲、
几何校验、容量不足不写、帧号/校验和可验证、两帧内容不同、padding 为 0。

**诚实地界**：这是**测试图案**，不是镜头/CMOS 数据，也**不会**让原固件认为成像就绪；
power-on inhibit 与 `ee_status` 保持原状。下一步才是把它接到 pin 缓冲通路，
并把模型里硬编码的 `pixels_consumed=0` 换成**真实计数**（由消费者回读证明）。

## 21. 成像像素通路：有限运行观测与根因推断更正

三条独立证据（同一 run，`run-gyzaujht`）：

1. **pin 缓冲只有 80 字节**：`BUFFER_WRITTEN ... bytes=80`、`physical=0x500000000`、
   handle `0x8000`。这是**控制/消息缓冲**，装不下任何图像帧。
2. **像素 SID 从未出现**：文档所指的像素通路 SID `0x82830752/0x82830753`
   在该 run 中出现 **0 次**；目标 SID 分布只有
   `0x92840747 / 0x81cf61c5 / 0x90030001 / 0x90590818 / 0x905a0048 / 0x909a015a` 等控制面地址。
3. **pinmem commit 写明 `pixels_consumed=0`**（模型里的诚实标记，不是遗漏）。

上述观测不能单独证明这些事件的因果顺序，更不能推出必须“设备侧先报传感器就绪”。
此前把它断言为闭环并指定CP前端为唯一修复方向，证据不足，撤回该结论。
CP 侧确实包含以下名称：
`[CAMFW] IMX473 DRAM PowerSave`、`Camera::ImagerDrvParam_IMX710E`、
`ImagerCtrl_IMX710`、`SET_IMAGE_SENSOR_BARRIER`、`CheckSetImageSensorBarrier`、
`CLK_CMOS_IN`（均为 cpapp-b.bin 内字符串）。

字符串不是就绪消息合同。`IMAGE_SENSOR_BARRIER` 的真实setter/checker已定位，
其AP命名关联防尘设置；checker只比较模型字段并记录不一致，没有等待或首帧完成证据。
原“字符串偏移表”实际为Gamma LUT，完整更正见 `cp-barrier-static-correction.md`。
当前需要从AP进入EE运行态前的具体分支和子调用确定缺失条件，不能凭缺包指定CP根因。
向80B控制缓冲填图、写EE状态或伪造ready均无正当合同。

已交付并可复用的部分：`device-models/cmos-source.c`（合成帧 + 帧身份 + 计数，2 passed）
将来作为 CP 前端的帧源使用；`capture_gate_readback.py` 用于持续监视 19+ 项门禁。
在真实成像消费和原编码输出验收之前，不宣称能拍照，`capture_verified` 保持 `false`。
