# 大步骤 9：沿原消费者补齐成像、编码和保存

这篇解决尚未完成的成像链怎样逐边定位，不宣称 CMOS、镜头/AF、照片或录像已经可用。

变量见[索引](README.md)。下面地址用于阅读既有原件证据，不是允许调用内部函数或注入完成包。
native与full是独立路线：同名合同可互作调查线索，动态通过不能相互借用。

## 小步骤 1：先把 HUD、控制回复和真实帧分开

**问题 →** 原HUD出现、模式切换或EE控制回复容易被写成“成像已启动”。
**现象 →** 可见AF-S、J-FINE等OSD，取景仍黑，EE仍可能为0。
**误判 →** AF-S代表合焦；3003控制回复f000代表CMOS首帧完成。
**定位 →** 分别列原模式写入、控制请求/消费、模型提交和像素buffer的新内容。
历史3003请求及16B控制回复已有静态合同，但不含足够像素/freshness证明。
**解决 →** 记录控制层推进的有限证据，要求实际帧来源、租期和完成另立判据。
**剩余 →** 不预填f000，不写EE=1，也不拿OSD截图或主机场景图代替原像素。

## 小步骤 2：镜头快照要追到生产者，不能编一个“已挂镜头”

**问题 →** LensCommunicator返回有字段，但字段角色和正常拍摄链不同。
**现象 →** 外部维护查询op0/op1能定位，正常app初始化却等待另一条通知。
**误判 →** status3直接叫“无镜头”；把十字节字段当已知型号/焦距/光圈。
**定位 →** 正常CamUserIf先发4073到`0x90030001`，再等`0x80020002`上的2040快照。
AP登记2040本地指针不是向CP发送2040请求。
CP生产者按generation遍历getter拼包；长度与上游状态不能跳过。
**解决 →** 找到光圈从2040内201b+8进入AP事件+18c的路径，原F4编码为u16 400。
快门1/125为u16分子1/u32分母125；这些只证明编码，不证明设备查询已给值。
**剩余 →** lens/ISO实际backing、generation发布、AF/AE请求与完成闭环仍不齐。
不发送全零快照，不强兑promise，不把d018控制动作当2040已经到达。
新增lens-init-contract仅闭合传输/初始化骨架的静态合同；未实测完整快照、挂机或焦距显示。
不依赖旧报告所谓“第32项”序号来定义2044，原表pair与线上布局需分别核。

## 小步骤 3：从编码消费者反推 YC 描述符

**问题 →** 找到尺寸和handle，不知道谁提供实际像素。
**现象 →** `sdf_encode_jpeg@0x34f6fd0`读描述PA、长度和u16宽高。
**误判 →** 描述符分配/填写完成就是帧生产完成；猜NV12/RGB后直接喂数据。
**定位 →** 先核输入`+20/+28/+30/+32`，再追原DMM分配、ImageSize/YcState/OutTim填写。
**解决 →** AP描述符分配与填写已有静态证据；resize请求目的`0x82830752`，
接收端后来定位在AP侧`av-cam.bin`的`tsk_sdt`，内部再交`0x82830753`。
`av-cam`地址坐标为`0xffffffc001000000 + raw`，不能套CP基址。
源/目标地址解析到API+1a8/+1b0，仍只是局部处理路径。
**剩余 →** CMOS原始源、完整planes/stride/格式、最终DMA完成及帧新鲜度未闭合。
不能因接收端在AP就宣称传感器生产者必在AP；同样不能无证据归CP。
新增imaging-pixel-contract把对象、序列化payload与解码结构的几何/属性偏移分开。
还核到一条真实分段容量检查：按CanvasX×CanvasY及YcCompress算required，再核段容量减offset。
该检查不是位深公式，也不能由此推定单plane、字节/位顺序或连续内存布局。
像素freshness、generation/lease仍未闭合，具名codec枚举也不能直接绑定另一YC字段域。

## 小步骤 4：核“成功”路径是否真的检查了返回与 ready

**问题 →** 原包装器可能忽略错误，零初始化输出伪装成成功。
**现象 →** JPEG相关路径两次调用接收wrapper，不检查其返回值。
**误判 →** ValidState必须=1；或者status0自然证明拿到了有效帧。
**定位 →** 原直接调用点均给ValidState写0，已核JPEG函数没有读它再分支。
接收API报错返回与队列有效但无消息无限等，必须区分。
**解决 →** 撤回把ValidState当ready门的解释；核真实reply、长度与buffer所有权。
**剩余 →** status0/length0是否经后续打包仍生成非零总长，不能凭此局部推断。
“上层没检查”不是模型可以空ACK的理由。

## 小步骤 5：Still 编码队列与输出语义分开查

**问题 →** 从函数名推断`0x8057060a`必是JPEG执行器。
**现象 →** `mc_still_enc_encode_frame`的上游诊断又出现`encode_heif`。
**误判 →** 将reply+18的u64直接叫JPEG字节长度；把控制发送器当编码生产者。
**定位 →** 核发送指令、原qid命名、请求布局与回复实际读取宽度。
后续原布局记录请求头len=`0x60`，应避免早期“60B”的十六进制/十进制歧义。
**解决 →** 保留已证qid、`2003:010e`、状态+10和未知u64+18，不为字段补业务名字。
**剩余 →** 该队列实际receiver、编码输出写入、reply+18语义与格式绑定仍未闭合。
不能因AppFw直接搜索零命中就宣布所有镜像都没有接收者。

## 小步骤 6：Movie 先验配置往返，再追 ES/info 发布

**问题 →** EncOpen返回成功，仍没有帧或录像文件。
**现象 →** 原`0x8055001f`接收端是InfraAvbbcIf，继续转Movie encoder与下游MCODEC。
**误判 →** `0x8055001f`就是H.264执行器；EncOpen新分配了输出或已经编码一帧。
**定位 →** 记录调用方预先提供的ES/info/status缓冲及viewId路由。
再核writer取得info条目、payload长度、真实搬运完成、sample登记和写出字节数。
**解决 →** Movie控制配置、原软件MP4封装与Fsys_Write/WriteAndFlush链有局部静态合同。
`WaitForVideoInfoAccumulation`在空列表也能返回0，条目存在必须另证。
共享读索引受最慢消费者约束，不能按“消费一帧就free”简化租期。
**剩余 →** 实际ES写者/info-WP发布、H.264执行、DMA完成和正常封口尚未闭合。

## 小步骤 7：到原保存链的终点，而不是仅看入队

**问题 →** 原异步请求入队成功，后台仍可能拒绝保存。
**现象 →** 原Still MPR构造写参数，经Fsys挂载卷写入，再走完成回调。
**误判 →** Linux路径写一个JPEG就算原相机保存；Still和Movie共用同一个写API。
**定位 →** Still从`libmpr+0xf20ec`调用前核路径/总长/段表，
到Fsys实际判定长度，再到`libmpr+0xe81ac`完成状态，关联同一个请求。
Movie另走Fsys_Write/WriteAndFlush，不能套Still专用WriteDirectFileAsyncV2链。
**解决 →** 原文件系统已挂载卷是保存前提；数据库/XML只能证明部分卡通路。
full早期“通知仍未到达”已被后续有卡payload及挂载实证更新，不能沿用成最新阻塞。
**剩余 →** 尚无原固件生成的有效JPG/MP4，输出路径存在、文件扩展名或宿主生成图都不够。

```bash
# 执行目录：$FULL；只读跳到合同中的纠正和保存边界
cd "$FULL"
rg -n '^## |重要更正|总长度 0|Fsys_Write|ValidState|MCODEC_2' IMAGING-CHAIN-CONTRACT.md
```

## 小步骤 8：从当前真正卡住的一条边继续

**问题 →** 多次零命中或send0，容易无差别重跑或注入固定完成。
**现象 →** full现场后来证实CameraBackground在状态1消费本地查询，发CP3007，等动态回邮。
**误判 →** worker条件变量空闲就是启动业务阻塞；同址复用回调当同一实例。
**定位 →** 绑定原回调生命周期、原发送、真实消费者state和下游等待，先排除探针重放错误。
**解决 →** full进一步定位到AP↔CP发送回调未注册的传输缺口，send0仍可能未离开AP。
native另有有限3007控制传输验收，属于它自己的显式模型及运行，不能抵扣full缺口。
**剩余 →** CP资源切换/实际消费、3006等完整状态动作与有效帧未因此恢复。
当前应补真实合同，不能用本地固定30回复或f000假装设备完成。

## 解决了什么，仍未解决什么

已积累输入、OSD、卡存储、部分快照/描述符、控制请求和编码/保存消费者合同。
没有成片闭环。MF+手动曝光+单张JPEG只是待查缩小范围方案，尚未证明足以拍照。
最终仍需原帧→原编码实际消费→有效输出→原封装/写入→完成→独立读回逐边验收。

## 证据入口

- [成像链合同，重点看§8、§10–13的后续纠正](../../../a7c2-re/report/2026-10-17-qemu-full-system/IMAGING-CHAIN-CONTRACT.md)。
- [full最新状态与传输边界](../../../a7c2-re/report/2026-10-17-qemu-full-system/STATUS.md)。
- [native镜头/曝光生产合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/control-lens-exposure-frontiers.md)。
- [新增镜头初始化静态合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/lens-init-contract/README.md)与[像素几何/容量边界](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/imaging-pixel-contract/README.md)。
- [native有限控制传输的独立验收范围](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/cp-background-contract/TRANSPORT.md)。

## 如果你在做别的机型

Sony消息、DMM/SDS、MPR和CP模块需按原件重核；不复制本页消息当成功回复。
可复用的是从消费者往回找生产者，把控制、像素、编码、封装、存储分开记账。
允许小步完成；证据不足时写缺哪条边，比把帧和ready补成常量更有用。
