# 统一相机开发批次

本批按用户要求合并开发与验收：并行完成组件及调用接线后，统一冻结、自测、集中修复、重测，再评估原固件综合运行条件。不按单个opcode、单个按钮或单个编码器启动VM。此前最新原运行仍为 `run-nzx01uc3`，不能把新host组件的输出回填到该run。

最新通过批次为`unified-camera-f3_eny7y`：**3253项通过、381个子测试通过、0失败**，398运行源、789项唯一冻结输入及全归档逐成员读回一致，构建和双原libc2.25 ABI通过。[本轮收据](verification-with-encopen-and-bank3.json)绑定实际observer `a053f67efe3f0add30fa9642340b84c00b12b9fb37020598b139b41053a898d1`、media及单独保存的binary/源码归档。原录像组件26项、bank3参数视图4项与实际bootstrap提取执行1项均在整批内；后者含正常、公有stage冻结拒绝、缺文件和config-copy错误4场景。

本轮实现两条已证接口：单EncOpen命令0/98h参数解析，保留P/V两个地址域、独立读/写控制区和完整byte88；以及[独立bank3的FLAGB局部源传播](../cp-parameter-state/INTEGRATION.md)。现有owned bootstrap显式执行constructor8→copy10→binding12→getter/STRB14，读回word2/FLAGB0，任何recopy撤销旧已知性；错误原样返回并保留bank0。辅助u16字段单位未证，解析器不把它当byte extent。前者仍为组件接口、未链接原runtime编码入口；后者不提升3003四数据、full76、ready或generation。

[原EncOpen生产者](../native-video-open-parameter-producer/README.md)新增12窗口/7086B正向证据：Md2d60明确写byte88=0；队列metadata在回调返回前存活。只有当该producer供应既有type0路由时，才可采用零分支；DMM unit3/4/6的metadata来源不证明逐帧YC/SDS或DMA lease。native gap63和capture=false保持，本批没有启动系统VM，最后原运行仍run-nzx01uc3/3003/EE0、无原JPEG/MP4。

后继[零分支START核查](../native-video-zero-branch-frame-input/README.md)为独立源补充：12窗口/6792B、14条指令、8状态行和8个分支目标读回一致。主会话对照旧source-record确认`14fcd4`返回S88编码输出数组，`136e1c`是其START配置运输，不能继续当YC输入追踪；元数据call地址已由误写136488改为实际134688，原指令字节未变。没有找到实际frame callback或可供native集成的新帧字段，没有重跑已通过的3253轮。首次仅收据目录缺失的落盘错误另行留证后已完成校验。

再后续两项源交付共22窗口/17,744B独立读回一致，未改运行代码或3253验收范围：[CP3003错误producer](../cp3003-error-producer/README.md)检查外层拒绝、guard和failure tail，仍只闭合16B/F000/四数据completion；没有可实施的合法错误包，内部-1/-2不转成wire错误。[CMOS/ISP→RC输入](../cmos-isp-resize-input-source/README.md)首次明确SOURCE T+08→J+10/address J+18和独立输入提交路径，上游为P+70/+78；旧T+90/J+98及P+80/+88是destination。仍缺P+70真正writer/帧owner、plane/packing和硬件输入解释。两代理均已交付，不再描述为运行中，也没有新增profile/ACK/VM。

前一通过批次为`unified-camera-hf09ecnj`：**3249项通过、381个子测试通过、0失败**，398运行源、764项唯一冻结输入与全归档逐成员读回一致，构建/双原libc ABI通过。[本轮收据](verification-with-vbb-normalization.json)纳入[有限VBB数值归一化](../imola-vbb-normalize/README.md)87行实际C代码及15专项，包括同一6组C场景原AArch64 libc执行；只有owned字节转换，没有寄存器/start/ACK/IRQ或像素消费。

本轮一并冻结original0/8420/conditioner/endpoint6至[硬件编程边界](../imola-vbb-hardware-frontier/README.md)、CPU颜色reader与[SPS Q网格语义](../imola-avc-sps-grid/README.md)。Q与实际P/B关联未证，因此没有新增猜测的像素geometry解析器；VBB方向/pitch/packing/completion和实际像素writer也未证明。归档SHA=`e3a78b8740ae3ac54d165c9173008eabd7a82d0342d0f2109ef383a8a604d5c6`，运行源归档SHA=`6cd0b2ae13e4ad290682300ae051f5d2082cabcbfbe9858bdffcc824861c54f0`；observer仍30eae41e。最后系统VM仍run-nzx01uc3/3003/EE0，无原JPEG/MP4，capture=false。

当前验收条件与所缺最小证据集中列在[CURRENT-BLOCKERS.md](CURRENT-BLOCKERS.md)。后续[VBB输入配置](../imola-vbb-input-configuration/README.md)只证明mode/参数写入来源，不能给gate0或读写方向赋予未知语义；[AP3003失败路径](../cp3003-ap-failure-contract/README.md)已证立即发送错误fatal，未找到合法降级，不制造非F000packet利用caller容忍。[LIF初始化前缀](../lif-initialization-prefix/README.md)仍不能赋M/C值；P publisher正常返回仅0/1fd87e0，不能倒推早期oldP；989d5c初始化目标已闭合为无M/C副作用的参数getter。继续寻找具体M/C值writer，不强写ready。

后续独立源补充见[header当前job队列](../imola-header-job-queue/README.md)和[具体dispatch](../imola-header-dispatch/README.md)：8407去conditioner1b，同D的8421才去header19；F是header prepare第二参数。关系仍受opaque worker selector和实际header选择条件约束，不推广P/B像素单位。这些补充不回填上述3249轮。

前一完整批次`unified-camera-o09vfdf9`：3234/381，398运行源、744项唯一冻结输入与完整归档逐成员读回一致，构建/双原libc ABI通过。[本轮收据](verification-with-alh-mbp-transport.json)新增完整ALH公有属性接线和[MBP双向两字传输核心](../imola-mbp-mailbox/README.md)53项（20个实际C场景在原AArch64 libc执行）；状态只知道0xA、其他位unknown、无CPU-MMIO/IRQ或command20自动执行。ALH与mode/profile同stage/guard原子消费，index0x29=41，worker当前gate仍未知。

[ISA核查](../imola-ipsx-isa/README.md)两项检查与canonical64静态反编译成功不作为CPU型号或厂商操作语义证明。当前归档SHA=`1a2b740b033c9b315c77e44045e3db1d7f8fe589d5b1a3ad25b7e0a0b30d0d01`，运行源归档SHA=`812c8fcdfaf5199c7a4377e5aab19772d2eb36951d941ae5ca47b0446c4dc6a8`，observer=`30eae41e5e5b6078496cbec81dc9fab17ec17b9f45857ac7163c5d7d579d04ed`。后续[AVC真实命令块构造](../imola-spu-encode-block/README.md)、[派生AVC original0条件地址绑定](../imola-source-frame-binding/README.md)、[原CPU颜色reader/有界JPEG调查](../cpu-jpeg-codec-evidence/README.md)、[original0到VBB8420请求](../imola-original0-vbb-request/README.md)、[endpoint1b conditioner至endpoint6条件转发](../imola-venc-request-conditioner/README.md)为独立只读源合同，不倒算本轮。地址条件链已闭合，实际子类、pixel writer/stride/packing/bit-depth与ES目的仍缺；通用格式reader没有camera lease绑定。最后实际run仍3003/EE0，无原JPEG/MP4，capture=false。

前一完整批次`unified-camera-ladne230`：3179/381，398运行源、731项唯一冻结输入与全归档逐成员读回一致，构建/双原libc ABI通过。[当前收据](verification-with-imola-static-banks.json)纳入[独立Imola MIPS静态bank工具](../imola-mcu-firmware-contract/README.md)19项及[IRQ41/128B完成环/0500源合同](../native-imola-output-source/README.md)。已实际导出认证RAM0并静态反编译原producer-index发布函数，没有执行MCU。硬件别名、状态/IRQ生成及真实编码ES字节来源仍未闭合。

当前全部输入归档SHA=`684baee22d39ceee17fea1cb0d7d638f9ed9e8e259bda8de3d5d346def44dd0a`；运行源归档SHA=`a5f874fb3921ddacf0ee0f0e4578375c1d6a8ffaec07612a63a351861bd781bd`。后续[MCU上游AVC接口](../imola-mcu-encoded-source/README.md)只读交接不倒算进本轮。它已到8880/AVC record与CPU计数writer，实际MBP packet、像素格式/地址及硬件kick/completion仍缺；尚不能拍照写卡。

前一完整批次`unified-camera-81k8m3cs`：3160/381，398运行源、725项唯一冻结输入及全归档逐成员读回一致，构建/双原libc ABI通过。[当前收据](verification-with-source88-writer.json)新增[实际S88 CPU writer组装](../native-video-record-fill/README.md)与原生011c通知计划，19项专项含七组C场景原libc执行；工作项、实际段长度、metadata时间排列及S54..57保留字节均有检查。原[BSO_DONE到620 CPU结果构造](../native-video-engine-result/README.md)及回调注册已查清，但实际结果指针内存、ES字节及0500事件生产仍未闭合。发现独立Imola MCU固件，后续只读核其MIPS ROM/主程序装载映射，不将资产存在当作已执行。

3160轮完整输入归档SHA=`b26ba26952eb7f7e3bc9112171922966fe9d946f1be9ab79016442c82ded65bc`；运行源归档SHA=`95abec6e545c5e0b30fa18b8e78650d17b90a2bef3fe36799f2d7c24bdaa1687`，实际构建物独立保存。原系统VM仍未再启动，无原JPEG/MP4写卡，capture_verified=false。

前一通过批次`unified-camera-u298jyxc`：3141/381，398运行源、713项唯一冻结输入及完整归档逐成员读回一致，构建/双原libc ABI通过。[本次收据](verification-with-single-decode.json)记录新增的`lif_cache_receive_with_handshake`：同一真实动态解码同时提交缓存与条件握手，旧只读API不变，三owner/backing/输入/输出失败原子性有验证。缓存37项专项含34个C场景原libc执行，视频七组C模式也成为正式原libc回归。后写非空字段表、token/opaque与slot incarnation各自保持来源，state5不变为ready。

前一缓存批次`unified-camera-scn8kfgp`为3136/381、711冻结输入，保留[独立收据](verification-with-cache-admission.json)。此前`unified-camera-jvyiv8f1`：3103/381、398运行源、697冻结输入及逐成员归档通过，保留[收据](verification-with-handshake-and-producer.json)。后续能力不倒算进这些历史轮。

3141轮完整输入归档SHA为`a12f9992296e121f9bdcd03aaed5bae61baf604459c7bc9c4f0b857aa35142c4`，运行源码归档SHA为`131d0b84a8e84cbe4a775a032db8dd78bc012d4442b12d82a78fba22102016be`；测试输入与实际构建物均在当前批次目录独立保留。原固件系统VM仍未再启动、仍无JPEG/MP4拍照写卡证据。

3103轮扩展了以下源数据边界：

本轮扩展[LIF握手](../lif-handshake-contract/README.md)：独立reset写、命令9立即/延后处理、event9实际body重放和真实动态5/6解码的条件状态推进；能力/握手33项专项通过，全部28个C场景另在原AArch64 libc2.25下执行。新增[普通NAL四字节长度验证](../native-video-length-format/README.md)20项和[原88→96元数据转换/发布计划](../native-video-producer-contract/README.md)17项；组合自测实际处理跨环AU字节及最慢用户归还计划。原[双控制区字段](../native-video-shared-binding/README.md)已查清，异步指针传递仍缺；[JPEG SOS与restart边界](../jpeg-scan-restart-contract/README.md)不清除ASIC gap2。这些不证明实际CP发布、编码像素或原媒体落卡。

同一3103归档中的原元数据/环/AU/参数集/长度验证C源码又直接链接原libc2.25，在QEMU用户态执行了全部7组视频C场景，包含跨环组合数据链。逐源码摘要与已冻结输入全等，补充[执行收据](verification-original-libc-data-path.json)单独保存；不增加host回归计数，也不视为原固件拍摄或系统VM验收。

此前`unified-camera-dpe5i2p7`为3055/381、398源、674冻结输入，首次纳入能力owner/AU视图/VideoInfo环，保留[独立收据](verification-with-lif-and-video-inputs.json)。

此前`unified-camera-c8lxht7i`为2994/381、398源及649冻结输入，保留[独立收据](verification-with-cp-stage-and-paramsets.json)。实际CP initial stage的mode/profile、同stage参数导入决策、694字节common与2223字节默认本地写、独立d64复制及bank0绑定已接observer；[组合输入合同](cp-owned-input-stage.md)记录2913已知参数字节、与真实4063组合2973已知/455未知的边界。另新增[严格type4参数集解析](../native-video-paramsets/README.md)。先前2993/381虽测试通过，但原libc无fstat导致构建失败；修复为既有AArch64 __fxstat ABI后才通过本轮，失败轮独立保留。

当前observer为`95db1a9d5b66f99a15bedc284727223b4ab4c39a5fbe0b8f0db607339a333b78`，3103轮运行源归档为`ccefa34fe58e599afded12a41186bf82203d26bb6b0066e99a3e28e4277a716b`，全部697项输入归档为`2b284609a0aa0d5144a68a0c6805dbd0242acf5c41f43822d31bf78c12ec918e`；它们与media均在3103批次目录单独保留并读回摘要。原2994/3055轮产物和收据独立保存，不倒算新能力。仍未启动新系统VM，最后实际运行仍是run-nzx01uc3的3003等待、EE0、无原JPEG/MP4，capture_verified=false。

前一输入合同批次`unified-camera-9qz_swqz`为2923/356，383源、608冻结输入，保留[原收据](verification-with-native-inputs.json)。该批推进了四个独立边界：

- [LIF帧解码](../lif-runtime-input-contract/README.md)：原帧头/长度/校验、命令5/6动态字段、16字节真实发送位图与type1完整u8源门均有检查；输出拥有完整副本和字段offset。组件未接原接收producer，不推进CP状态、ready或ACK。
- [原JPEG逻辑尺寸](../native-jpeg-binding/README.md)：原任务的ADD偏移与P+28尺寸副本、成功后SOF0写出已闭合，新增参数解析器校对W16/H8而保留未取整尺寸。15项严格/SAN/真实解码测试，包括128组几何、289×17边界和逻辑尺寸对应MCU熵的精确裁剪。YC/scan缺口仍未解除。
- [参数reset源写事件](../cp-override-input-contract/README.md)：CP8db6d6显式STRD零写覆盖P+1c8的8字节，virtual-owned-state在首次批次前消费这一步。普通init仍全未知；完整constructor、后续作用和发布均未完成，日志明确initialization_complete=0，四字节provider仍0/4。
- [RC目标合同](../rc-destination-layout/README.md)：原JPEG转换分支selector0、目标byte地址/2*W步进及DMA字段已闭合；分量顺序、plane数量和真实DMA lease仍未证明。7窗口provider证据与新增12窗口目标证据分别归档，未用其他VDT路径的descriptor值代替本路径。

该历史批observer为`63680dafd2edd98da0303839676fbc6333d45e4db1a797be8bea40c8de7761d6`，media仍为`38361f057de51d5349d2572b0ab1bcc2bb65a9675e83f97459672333dc81d66e`。归档SHA为`d9426091cc2e2b673e47a003842fac469851f2e41cb77e3c4de4407a807f227c`。LIF模块归档并自测，尚未连入observer的原接收路径；原ABI通过覆盖本轮实际observer/media产物，不因此声称LIF已原生消费。该批代理均已结束并收取；当前新增模块的并行开发与其分开记录。

## 已接的代码

| 部分 | 实际实现 | 原生边界 |
|---|---|---|
| 光学与帧 | [帧owner/对比度AF](../virtual-optical-frame-owner/README.md)：真实optics_render、帧代次、单lease、ROI对比度17次粗扫及最多12次细化 | 显式虚拟RGB888；不等同原Sony YC、SDS或CMOS IRQ |
| JPEG | [源编码配置执行核心](../virtual-jpeg-hardware/README.md)：原表/422帧头、真实压缩、SOS写回/读回、lease释放后IRQ；[原寄存器绑定](../native-jpeg-binding/README.md)：quant/Huffman/AIF、W1C、FIFO和原状态优先级 | 原START仍因YC布局/lease、scan/restart及同提交原参数快照未接线而返回NEED_DATA；逻辑尺寸解析接口已实现 |
| 录像 | [逐帧H264/MP4](../virtual-video-engine/README.md)：RGB实际转换/压缩、packet复制、PTS/DTS、EOS和有界内存mux | 原MPR/codec DMA/IRQ/Fsys调用接线未由host组件证明 |
| 原录像协议 | [MPR/Avbbc绑定](../native-video-binding/README.md)：48 B请求、单EncOpen的98h原参数解析、独立控制基址、96 B VideoInfo、Sampletype64已证成员、有界blob拷贝、实际H264 packet桥、[type4参数集](../native-video-paramsets/README.md)、[普通AU两段视图](../native-video-au-contract/README.md)、[四字节NAL验证](../native-video-length-format/README.md)、[88→96生产元数据](../native-video-producer-contract/README.md)和[最慢用户索引计划](../native-video-ring-contract/README.md) | native请求仍UNSUPPORTED/gap63；容器期望格式和元数据源算法已闭合，实际编码载荷、frame/SDS、YC、硬件lease和异步发布身份仍未证明 |
| 原异步写卡 | [MPR/Fsys合同与验收](../native-card-write/README.md)：精确0x508请求/iovec/fileSize截断、真实callback/worker返回透传、同owner原Open/Read/EOF/Close、宿主SHA/FNV与独立JPEG/MP4解码 | 只建立观察/读回与验收能力；未有原媒体请求/产物。物理地址内容模式明确不支持；未观察、失败或超限均拒证，不能由still回调推断视频生产恢复 |
| 组合管线 | [统一像素管线](../virtual-camera-pipeline/README.md)：配置/AF→帧lease→JPEG或逐帧H264→输出读回/packet sink→MP4 | 两份JPEG及2/4/6帧H264/MP4在内存独立解码；没有写host照片冒充固件拍摄 |
| 参数 | [190槽字段消费者](../cp-parameter-state/README.md)：303描述符、common/default本地写及独立config/semantic掩码 | 纯4063路径891已知；本地初始化组合2913已知，与真实4063组合2973已知/455未知；完整constructor/发布仍未证明，保持PARTIAL、不增generation |
| 启动数据 | [四字节状态owner](../cp-start-state-data/README.md)：真实tuple/flags/action/override算法、property/ADJ/Q/getter事件；[属性provider](../cp-start-state-provider/README.md)：有界BK4解析和256 B真实payload读回 | 实际mode/profile已从显式CP initial stage消费，独立参数view已绑定；四结果仍0/4，真实LIF/history/M/C等输入未闭合。旧file-primary缺属性时不自动fallback |
| LIF能力输入 | [能力owner](../lif-capability-owner/README.md)：实际公开stage、01/07/08/3d帧复制369字节、支持缓存刷新与独立K本地写事件，再导出给位图builder | 有源握手本地链与boot event9入队已实现/查清；原帧到cache admission、实际event执行/worker发布仍未证。context[0x20]=1时受未知纯getter影响的位保持未知，model state5不变为ready |
| 完整快照 | [76块assembler](../cp-full-state-snapshot/README.md)：全表/尺寸/头/同代/已知mask及镜头域；[发布后端](../cp-state-publication/README.md)：3003/3000真实16 B、mode1 ACK/2040独立lease | 不能用布局组包替代76块实际provider；当前full provider明确ENODATA |
| 输入 | [实际UI/串口owner接线](../camera-input-coverage/README.md)：键鼠触控/拨盘、按下释放、半按全按顺序、失败释放保留、丢焦/关闭清理 | 无已证独立曝光补偿/AEL原contact，不虚构wire；原固件消费仍须综合运行 |

## 状态发布约束

新精确开发profile为 `virtual-cp-owned-state-v1`，复用A7C2_CP_CAPTURE_FORMAT/MENU_CP_CAPTURE_FORMAT，默认关闭、完整前驱依赖不变。构造只初始化自己的unknown状态，不导入ready、current、模块完成或旧run成功。

实际4063除保留原stager外，会调用新字段消费者并记录覆盖；config消费与完整business应用仍分开。3003数据只有source owner四字段全部已知才可构造16 B回复。mode1须完整76块同代输入，先校验再ACK/通知。完整2040的shadow只在原receive匹配全部正文且实际receiver线程free0后推进，不以send0当消费。

当前没有借用属性secondary的自动fallback，也没有把显式虚拟属性仓库选择当原CP选择证据。固定光学profile、模拟帧存在或host编码成功都不供应未知的CP控制状态。

## 统一验证结果

最新写卡轮 `unified-camera-woquvyjt` 为 **2911通过、356子测试通过、0失败**，380份运行源码构建，592项唯一冻结输入再次读回相同。新检查器82项、受影响媒体组92项/52子测试均在此整批中，含源合同重复JSON键拒绝回归。原observer及新media preload分别通过原libc2.25 ABI；media以`LD_BIND_NOW=1`实际加载并解析全部导入。media SHA-256为`38361f057de51d5349d2572b0ab1bcc2bb65a9675e83f97459672333dc81d66e`，原observer仍为e7e890。归档SHA-256为`28e1e64fdfd3a5378653a609d6678d37bdfef9f222fed5c207db291b730bc24b`。结果见[写卡批次汇总](verification-with-card-write.json)，其SHA-256为`449225134778b1ce1d84622373a0d1c018f5f1ccd46f1cb04dd0cf9cad67a767`。

原MPR/Fsys合同已核19个窗口/34,700字节及2个回调GOT绑定。描述符是物理/虚拟地址与提交长度，不含文件offset；fileSize来自独立u32字段，原写入按顺序拼接后截断。回调0x4d8结果是磁盘统计，不含实际写入字节数。原Flush会排空Fsys和真实回调，但不join MPR工作队列，也不关闭新写入准入；验收器因此逐token检查callback和worker返回、全部原生读回及最后coverage。该检查器始终不认证CMOS/原编码来源，`capture_verified=false`。

此前完整写卡轮`unified-camera-72luu9q0`、纳入共享reader的`693gii0a`及新增flush窗口的`45wa7f6c`均为2910/356通过，收据分别保留。`ksndcrgj`测试虽为2910/356通过，但验证期间输入变化，整批拒证且没有ready.json，未改写为成功。随后修正源合同重复`mpr_builder`键并增加拒绝回归，再冻结得到最新2911/356。中间曾有1项旧上限fixture断言失败：它仍期待32条后无日志，而新要求必须记录coverage incomplete；已修正断言并保留失败证据，没有移除漏记保护。聚合报告的旧摘要与窗口计数也已按同一最终收据统一，历史记录保存在`runtime/analysis/scratch/native-card-write/reconciliation-issues.json`。最后真实运行`run-nzx01uc3`经新检查器只读检查，明确返回1：`no native original-write evidence; host media is not capture`。旧run未改、无新系统VM，生产和候选QEMU摘要保持，两个既有锁可实际独占。

加入原录像绑定后的此前一轮 `unified-camera-h8l9gn31` 为 **2819通过、304子测试通过、0失败**，378份运行源码构建与原libc ABI通过。582项冻结输入再次读回一致；新增23项原录像协议/实际H264 packet桥测试已纳入整批，而非仅独立报告通过。

最终观察器仍为 `e7e890dc2c4d48edd266f4ebbaf8a48b9157a72aab47da4e893369f1d45d8b97`，本轮归档为 `fdb279c7c981f4b292bb4d71e545284ad179fdf161f6fd588031f5a07e062115`，回归收据 `4b8493896ee89bd512844dc6c5bf1659ec56fec99ab25a288a33a781ddaf9511`，ABI收据 `b329d000e6fc179f1ae8d7c47d5b3f3ec8786296204a93829cdd1a7b5c6bb6bb`。独立 [最终汇总](verification-with-video-binding.json) 初始SHA-256为 `8a84b5386575abcf50c2036700cffaa915d752e0b9ef018b1f8d90b92cf904c0`。原录像native gap63、原JPEG START及CP实际provider缺口未被这些host通过记录解除。

首轮 `unified-camera-8hz949o1` 为2795通过、304子测试通过、1项旧接收fixture编译失败，冻结输入未变。集中修复该fixture的新依赖/顺序断言，并补实际接收观察hook保存恢复errno后，整批 `unified-camera-o702xix2` 得到 **2796通过、304子测试通过、0失败**。378份运行源码归档与已测试输入一致，观察器构建与原libc2.25 ABI通过。两轮日志/收据分别保留，没有覆盖失败轮。

观察器SHA-256 `e7e890dc2c4d48edd266f4ebbaf8a48b9157a72aab47da4e893369f1d45d8b97`；源码归档SHA-256 `cb62dfc11494a2debf1fff4b32c5694780234c5ad85fa4126ef400f59a5ffae8`。原ABI收据SHA-256 `2ed2e51b1c57fb809bc42367d94458c4c41ba1c78bfd95393af35488ecac24d4`，整批回归收据SHA-256 `b202006818e07fd5eeae1c614fd84aedc9957ab35d52415e928fa7fdf185b013`。汇总见 [verification.json](verification.json)，其初始SHA-256 `d182eb23e4f81fa7e8dec900e8aee42a3a608a21bd2729fd4d56625d21998a4b`。

本批没有新增系统VM。本项目没有残留system QEMU；检查时另一个workspace的zve10-qemu有其独立QEMU进程，汇总如实记录，未操作它。原生总验收尚不能通过：四字节provider的实际启动输入仍0/4、76块状态实际provider不完整、原JPEG START明确NEED_DATA、原MPR/Fsys没有媒体产物证明。没有把host组件的JPEG/MP4写成固件拍摄结果，也不为同一已知数据拒绝反复启动单项VM。

## 原生总验收仍缺的具体输入

冻结期间又完成两项只读核查，主会话独立核7窗口共1734 B，见 [native-blocker-source-pins.json](native-blocker-source-pins.json)。没有据此改变任何已通过测试的实现或known mask。

1. LIF实际mutable writer定位到CP135f88内137840..137870，确有条件地把kind/state/subcode和四字节flags清0，再于138b62调用a4bd3e发布。该路径受1107178模式和1a03ac0状态门控；未证明本启动前缀实际经过它，且action+128生产者和实际输入packet仍未闭合。因此不能将条件reset升级为构造默认，四字节运行provider仍0/4。
2. JPEG色度矩阵的选择表/21组系数和寄存器字序已闭合，但不能由矩阵反推内存Y/Cb/Cr的位置。先前候选K53864是完整的宽高比/矩形计算，非CPU像素转换。缺口精确为ASIC从B+800及其DMA步进读入字节、映射到B+2400三个矩阵输入的方式，以及plane/chroma组织；START仍拒绝。scan/restart含义与未取整逻辑几何也须和实际原请求保持一致。

后续主会话又核到action+128的条件清0：1382e0令r6=mutable，1382e8写回令r6=mutable+f9，13833e向[r6+2f]写r5=0。最近的零赋值为138250，至该store无r5改写。它补充了条件action赋值源，见 [lif-action-reset-source.json](lif-action-reset-source.json)，不证明本启动路径实际执行或完整LIF输入history。

参数初始化候选亦经原指令纠正：movw0160/movt0003组合为00030160，非03000160；35416c→be938e→55c0f0把当前参数写入property仓库，memcpy目的为property数据、源为原参数指针。它不是默认配置读出源，不能借公开secondary中存在4096 B零payload来填P+1c8，见 [parameter-property-direction.json](parameter-property-direction.json)。

1054像素producer关联也已推进：原libInfraAvbbc create_one_thumbnail先DMM分配1054，再把它作为resize的目标pixelSDS，完成后交Without_Pin编码；这是有据producer关联，但terminal RC实现以下的pixel byte/plane解释仍未证明，不能仅凭2×canvas或422帧头命名YUYV。

新调查已把原参数初始化的即时写与完整初始化分开：8db6d6显式STRD步骤现在有独立局部消费者；其后AE工作、flag0默认初始化及实际publication历史仍未完成，不能据此把override传给3003数据owner。公开secondary中的01250003=1也仅是存储内容，原仓库选择与交付未验证，见[lif-mode-property-source.json](lif-mode-property-source.json)。

此外，完整快照还有未实现的真实字段provider，H264组件尚未接到原MPR/codec DMA/Fsys录像路径。曝光补偿/AEL没有已证独立原contact，输入覆盖不会虚构它们。这些是未完成功能，不能用host内存JPEG/MP4或全量组包器的通过记录替代。

## 统一验证入口

```sh
cd runtime/analysis
python3 -B scratch/validate-unified-camera.py
```

该脚本要求全部组件/模型测试已落盘，冻结原控制baseline、所有新实现/测试/相关报告以及真实UI/运行入口。每轮独立创建 `scratch/unified-camera-*/`，保留inputs/完整日志/失败收据；不覆盖旧run或失败日志。只有全回归通过、源码一致、观察器和media preload构建及二者原libc2.25 ABI通过，才写本轮ready.json。它不启动VM，也不把ready.json称作原生拍摄通过。

最终综合验收仍须原AP/SDK请求消费真实帧，经原编码/DMA/IRQ与MPR/Fsys写入256GB目录虚拟SD，双原flush、文件摘要及独立JPEG/MP4解码成立。当前不满足这些条件，`capture_verified=false`。

Evidence包括各组件的严格C11/sanitizer、真实内存产物独立解码、原件字节/调用链pins与本轮冻结收据；Finding为可执行组件与输入接线已合并，原生状态输入/像素格式尚有明确缺口；Path是光学帧→编码→真实输出消费，与原AP→SDK→MPR/Fsys链分别记账。后者缺证时不将前者提升为相机成片。
