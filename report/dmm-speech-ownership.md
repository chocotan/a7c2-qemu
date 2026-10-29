# native DMM 两槽：初始文字朗读归属证明与 CP handle ABI

2026-10-25，公开 ALLLANG 2.01，本机隔离 QEMU。

当前结论：`run-dru5iey2`完成同轮初始创建/epoch/引用历史/原AP表联合证明，
`run-ba2cnxt9`按严格资源域保留两块外部Speech缓冲，NoMem两阶段及原AP完成消费通过。
仍不授权释放外部缓冲、不证明AP映射/全局idle/原CP硬件或拍摄；新前沿为ADF0323，EE0。
以下保留各取证轮次与失败边界。

`run-sfl0pwn2` 在NoMem准入时读回native DMM两槽allocated=1/1、open=1/1。
当时没有生成路径完成，原请求正确保留为faulted pending；原AP继续等0149，EE0。
原Fsys三文件导出/摘要/clean commit及进程/双锁收尾通过，但没有JPEG/MP4。
当时完整创建/生命周期归属尚未闭合，不能释放外来handle或忽略活跃引用。

## 已取得的实际绑定：run-pbg8l3g4

CP handle修正后，实际op20分别返回 `8400/8401`、gen1、CP地址 `1e000000/1e080000`、
长度各80000、opens各1。原AP朗读表 `5f66b08` 两次144B原字节相同，SHA256为
`c913dba132cee156dce1407420bdb241564af2c6f6d6554a7c0acfc7f6061523`。
ID1a/1b中的CP handle/长度/地址逐槽精确匹配；AP handle为405/406。
`tts-dmm-evidence.json`保存基础关联，仍保持创建链、AP映射、全局idle、释放与拍摄标志false。

这没有改变NoMem guard：两槽非空仍refused/pending，无APPLIED/QUEUED/REPLY_FREE。
Common仍等0149、EE0。HUD/自然快门输入/原Fsys三文件导出与全树摘要通过，
`dmm-tts-cleanup-assessment.json`核对owner/组/QEMU退出、双锁可独占，未用SIGKILL。

实际创建日志只有通用底层caller `appFw+35522a4`，不能单独证明上层来自Speech；
单纯5位世代/固定地址/双读相同也不能排除31轮历史复用或`1→2→1`引用变化。
独立设计复核要求先闭合这些条件；该轮尚未增加非空池的放行分支。

## 同轮联合证明通过：run-dru5iey2

修正首设内容等待后，同一bffd observer重新完成HUD、自然快门输入和原Fsys导出。
强验证器实际通过：AP PID258，两个独立40B请求各自先于本次4帧与完成；
前四原saved-return-PC逐项匹配初始Speech，返回8400/8401；epoch1/2、creator1/1、
allocations2、lifecycle_changed0。原AP表两次144B相同，SHA256：
`c733a7e080b4f542d5ce1d031bbdf3428440e85b11863d94c23572ecf0fc9dd5`，
ID1a/1b与两个live slot的handle/世代/地址/长度全部吻合。
`tts-dmm-evidence.json`记录creator_call_chain_verified与initial_speech_lifecycle_verified=true，
限定为4个有界原返回PC和请求/epoch链，仍不是完整unwind。

本轮仍维持旧pool-empty判据，所以NoMem继续refused/pending，无路径应用或AP完成消费，EE0。
三文件全树字节/摘要、原Fsys flush、clean commit、owner/组/QEMU退出、双锁可独占均经
`initial-speech-provenance-cleanup.json`核验，未用SIGKILL。
AP映射、全局DMM idle、释放授权、VEF与拍摄标志仍false。

当前已具备为本实例初始两块外部Speech资源建立隔离的证据。
后续准入仅可接受“已知空池”或这个精确的首次Speech域，继续检查NoMem自有无效缓存、
extra/context/work及其它共享控制工作排空；不释放、不清零、不重映射Speech资源，不冻结其数据字节。
任何未知producer、重初始化、引用变化、部分表、世代/epoch复用仍拒绝。
新资源域代码已通过相关127 tests+31 subtests、独立review3cd和ARM ABI源码链。
`run-ba2cnxt9` 实际再次通过同轮强Speech证明，domain2/foreign_speech_kept1准入，
NoMem两阶段及自身四个无效缓存/extra/context/work0读回完成；dmm_release_calls0，
精确005a0000外层回复实际queued并由原AP释放rc0/faults0/ap_consumed1。
三文件全树读回、cleancommit与所有进程/锁收尾也通过，详见
`nomem-qualified-evaluation.json` 与 `vef-path-frontier.md`。
这只建立虚拟NoMem控制完成，仍不证明AP映射、全局DMM idle、硬件或拍摄；
新Common前沿为0323 adf_proc_set_path，EE仍0。

## 原AP中的文字朗读数据流

AP `appFw.so` SHA256：
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
以下AP地址均为ELF VA。

- `1799594 → 17b2b10` 循环两次，分别申请 `{unit63a,chip0}` 与 `{unit63a,chip1}`。
  CP调用 `17b2c04 → 34d35e8 → 3552790 → 35521a0` 构造40B op20/option1，
  chip1选 `9061003c`。该路径留下两块本地AP缓冲和两块CP缓冲。
  重初始化路径 `17b06f4` 有同类调用 `17b07b8/17b07e0`。
- GOT `5b5c530` 指向原资源表 `5f66b08`：两个0x48B条目，ID为1a、1b。
- `17b0ed4..17b0ef4 → 34ddea8 → 359710c` 创建24kHz单声道Opus decoder；
  `35973d8` 调opus_decode，`3597438..3597448` 将PCM写入条目的AP缓冲。
- `17b1054..17b1070` 使用同条目的AP/CP handle走传输包装器；
  `17b0238 → 34c7498 → 34f07ec` 以CP地址构造BB0329。
  原名表 `58c8838` 的wrapper77为 `adf_sys_set_table_for_text_speech`，
  wrapper79为 `adf_sys_request_text_speech`。
- `17b29b8` 解除AP映射，再通过 `17b2a34/17b2a4c → 34d36e8 → 3552978 → 35523b0`
  分别释放AP/CP handle，清零条目；直接调用者为应用生命周期路径 `1799f74`。

这是消费者、数据写入及生命周期的证据，仍不能认定本次两槽就是它。
原NoMem缓存是CP accessor中0x90B描述符，结构/消费者不同；必须逐个实际handle绑定。
`libgpe.so+d208` 的63a只是错误日志编号，不能作为分配证据。

## 已确认并修复的 CP handle ABI 不一致

原CP `cpapp-b.bin` SHA256：
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，
以下CPVA的文件偏移为VA−108000。

| 原始锚点 | 证据 |
|---|---|
| AP `35523e8:bf0271f2` | free_core测试handle bit15 |
| AP `35523d8/35523e0`、`35523e4/35523ec` | 候选目的分别0061003c（本地）、9061003c（CP） |
| AP `35523f4:9402801a` | bit15清零选本地，置位选CP |
| AP `3552470:150800b9` | 完整handle写入op23+8，没有删标记 |
| AP `35523a4:a00e40b9`、`35523a8:600600b9` | allocation从reply+c取完整u32，原样写out+4 |
| CP `C1E51E:40f40040` | 真正分配器OR8000 |
| CP `C1E50C:6ff39f20` | 低10位index |
| CP `C1E526:03f01f00`、`C1E52E:22f4f842`、`C1E532:42ea8020` | 低5位generation写入bits10..14 |
| CP `C1E53A:37f81e6c`、`C1E4AA:c9f80060` | u16零扩展，按u32输出 |

正确成功编码：`8000 | (generation << 10) | index`，高16位为0。
原CP `C1E4F4..C1E502` 的世代更新是旧值≤30则+1，否则回1：1..31→1，不经过0。

旧native `dmm-service.c` 生成0400/0401，缺bit15，且31后错误地到0。
已在唯一公共实现修为8400/8401，并跳过世代0；未改两槽容量、物理映射、
open/release计数、资源准入或Pin-control独立池。
这修复的是静态ABI不一致；**没有证据说旧run已经执行了错误释放或发生泄漏**。
不在已有VM中转换活跃handle，后续只用新实例从空状态开始。

`test_dmm_cp_handles.py` 编译实际核心selftest并启用ASan/UBSan，
核首两handle、CP位、u16界限、两次31→1、错误删位handle拒绝及原AP/CP字节锚点。
和TTS关联/NoMem资源相关检查共73项通过。

## 创建者与不可复用的首次生命周期证据（尚待新运行）

初版新增metadata不改DMM容量、wire协议或NoMem判据：每次实际成功分配使用单调u64 epoch，
slot保存本次epoch并清旧creator；计数耗尽在修改pool/内存前拒绝。
任何实际op21/22引用变化、op23释放（包括raw3）永久锁存lifecycle_changed；
op2a与无变更错误不改变历史。整体sender回滚仍包含这些字段。

原发送入口提供自身FP与原caller，reader只读自身proc/mem，最多8帧、对齐/单调/256KiB范围、
用户地址界限，且首帧LR必须等于实际caller；仅前16次分配尝试记录。
只有前四原ELF saved-return-PC精确为 `35522a4/35527b4/34d3614/17b2c08` 才标initial Speech，
重初始化17b07e4、未知/短链全部unknown。后三笔BL目标另由原AP字节独立核验。
这不是完整/已认证unwind；源字段明确frame_candidate_only。

强关联器 `prove_initial_creation()` 在基础表匹配上，还要求：

- 同一显式AP PID，两笔实际成功分配各自有独立40B原请求、正确unit63a/option1和动态source。
- 四条实际返回PC、LR与AP基址、caller、摘要、事件前后顺序逐一吻合。
- 当前pool恰为首两epoch1/2、creator1/1、allocations2，且无引用/释放/重分配历史。
- 任何缺字段、未知producer、重初始化、epoch复用、`1→2→1`、AP表变化均拒绝。

独立实现审查发现“一条较早请求可同时证明两次分配”的P2，已要求下一条请求必须在上一笔
完成之后并在自身帧/完成之前；新增只丢第二条请求、保留全部其它记录的反例。
相关94项host检查通过，创建者/epoch新observer源码链已按原ARM ABI核对。
当时只有宿主测试、构建及部分真实创建帧证据；实际NoMem检查时点的联合证明由后续run-dru5iey2取得。
该取证轮次NoMem判据未变。

### 创建链取证轮次 run-dxznsk9c 的分层结果

真实sample1/2前四saved LR均为上述初始Speech链，分别返回8400/8401，
creator_kind=1、allocation_count=1/2、epoch1/2、lifecycle_changed=0。
第三个unit62a请求的实际帧包含3021000/3209e48，确认落在LUT路径，状态-3而无pool变更。

首设自动化本轮失败，没有到NoMem检查点，不能把它与另一轮的表快照拼成同轮联合证明。
`creator-wizard-failure-assessment.json`保留两笔真实创建证据，原SD仅INPUT一文件，
导出/摘要/clean commit、所有进程组及双锁释放均已核验；不是照片或路径完成。

失败原因有原LCD对照：工厂记录1c6已出现时，latest LCD仍是底层可访问性页，
两个固定区域橙色分数均0；旧条件0≤0便发送DOWN。随后名为reader-do-not-set的截图
实际仍高亮“立即设置”（upper11234/lower0），脚本错误进入朗读设置页后反复确认。
旧文件名及原失败proof保留，不回填成正确选择。

GTK测试导航现等待真实模态边框、真实上下选项高亮；最多一次DOWN，看到“以后设置”高亮才允许ENTER。
12次刷新有界，最后一张也读取；未知/超时不确认，旧页同位置橙色不够。
6个相应边界情形及实际原LCD回放已验证；相关26 tests+13 subtests通过。
这是测试导航修正，不写原AP/固件gate；随后同一observer bffd候选完成run-dru5iey2联合证据采集。

共享logger曾只有768B，完整双读779B会截断；已扩大到1536B并确保超长记录保留最后换行，
通过实际record()的C格式化输出再送关联器回归，独立复核关闭该P2。
早期ARM构建另因缺memcmp声明失败，原日志保留，补声明后ABI/源码身份通过。
未把任何失败构建用作运行证据。

## 最小原生取证

已增加只读日志：原 `osal_snd_msg` 将自身原caller传给 `dmm_send`，
通过已解析dladdr记录模块/ELF偏移及PID/TID；实际请求与40B回复结果的handle、
地址、长度、状态和两个slot/open读回进入控制台。
没有把dmm_send内部返回点误当成原AP调用点；dladdr保留errno。

SetPath共同gate中，对原AP `B+5f66b08` 的0x90B做前后两次读取；
记录所有原字节、读取返回值、地址和unchanged标志，明确 `atomic_snapshot=0`。
未修改原表、资源或准入。条目已由原load/store核实：

| 条目偏移 | 类型/意义 |
|---|---|
| +0 | u32 ID 1a/1b |
| +4 | u32 AP handle |
| +18 | u32 CP handle |
| +1c | u32 CP长度 |
| +20 | u64 CP地址 |
| +28 | u64 AP映射地址 |

`runtime/analysis/tts_dmm_evidence.py` 是只读关联器：
仅在唯一、完整、前后相同、地址正确的两条目与同线程已绑定DMM快照中，
逐槽核对CP标记/u16界限/非零世代/完整handle/不同index/长度/物理地址。
旧缺bit15、世代0、越16位、错地址/长度、重复或变化快照均拒绝。
成功的基础关联保持创建链未验证；只有新的强证据也通过才设置
`creator_call_chain_verified/initial_speech_lifecycle_verified=true`，并标明仅验证四个有界原返回PC及
请求/epoch链，不是完整unwind。无论哪层成功，AP映射、全局DMM idle、释放授权、VEF路径与拍摄标志仍false。
它本身不能放宽guard或授权释放，只提供下一项归属证据。

准备好带上述日志的新run后，在 `runtime/analysis/` 执行：

```sh
python3 -B tts_dmm_evidence.py menu-runs/<实际run目录>
```

输出 `tts-dmm-evidence.json`；强证据未通过时保留基础关联及provenance_reason并返回非零，
缺失/变化的基础数据覆盖旧成功，不回填推测。
同轮强证据及随后NoMem原AP消费结果见前文；隔离只针对已证明外部Speech资源，
不释放或清零它们。

## 两条已分开的边界

- CP bit15修正不会改变Speech初始映射：它映射chip0/AP本地分配，`17b2c24`取该物理地址，
  经`34d37e8→3552f54`直接open /dev/mem、mmap，无CP地址加4G或ATU分支。
  原映射函数不检查MAP_FAILED，故非零表指针/状态0不足以验收映射。
  CP地址减4G来自本native模型策略，不是这条原AP初始映射转换。
  后续实际传输 `17b1054→34cb5e8→3514f54→interchip_transfer_async` 到02820746另未验收。
- 本run另有unit62a分配status=-3。原AP静态指向1bd `sequence_lut_memory_alloc`、用户3D LUT，
  公开DmmCfg的extent6db长度bca0（48,288B）。该错误会保留AP缓冲、CP handle无效并继续队列，
  不证明它造成当时NoMem/EE0；run-dxznsk9c实际创建帧已包含3021000/3209e48，且没有改变pool。
  没有为这个非当前直接阻塞新增假分配或成功回复。
