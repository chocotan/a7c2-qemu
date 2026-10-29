# 原3007之后的3006：当前阻塞与公开配置证据

原run-dx52p7qy已经实际消费/释放有限3007回复；之后上游`type12/wordC42`产生原3006。libObj `ee600`设置3006，`ee608`跳到共享尾`ee6f4`，绕过相邻301c设置，再调用ed9c4，解释当前CameraBackground的eda8c←ee6fc←ee82c栈。晚LCD黑、APO1及StillCa初始输入0都保留，不把有限控制成功当整机恢复。

## 原控制路径

CPVA=RAW+108000。实际3006映射family0/event3，完成映射family1/event303及独立b2298c producer，普通caller传f000；不是复用3007的event304。byte1/+8..23未被本命令读取，未初始化尾部不是参数。

current0的provider3669d8按键0051001d选择：0→路径`0→1b→1`，非0→`0→1`。两路径均有必选非零模块：

```text
0→1:
0101 0201 0301 0401 0501 0601 0701 0960 0a00 0b01 0d00 837f

1b→1:
0201 0301 0401 0501 0601 0960 0b01 0d00 813e
0110 0701 0a00 8041
0101 8001
```

mask分别037f，或依次013e/0041/0001，不能沿用3007的mask0推进。0→1b还有键003100a6选择的六个ROM变体，其中1..4含0105、032x/0361与021b等不同等待；0/5虽共享序列，也不证明某个是默认。完整原序列/地址和失败纠正保留在`scratch/cp3006-next-contract/PHASE2.md`，未执行原代码。

`verify_cp.py`从支持原件重新提取两条path、两份固定transition及全部六份动态生成候选的完整广播/mask，复现不依赖scratch转录，也不执行原代码：

```sh
python3 report/cp3006-start/verify_cp.py
```

原start还有独立92a20845事务/detection状态、G+58对象的真实字节门槛、执行准备callback、prepare/busy/generation等。slot0的0101/0110虽在共同准备通过后不增加新帧判据，其它必选模块仍须自己的真实消费者/完成，不能把0301等回显成observed。当前正闭合两路径都需要的slot1/0201。

## 只读公开seed核验

唯一读取的数据文件是官方更新包`0110_backup/SYSIPSX-DSLR/PP/CX89701_ALLLANG.bin`的原样seed副本，2390264B，SHA256 `3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`；与prepare-assets的硬编码来源/manifest相符，不是真机Backup.bin或private setting。脚本先拒绝任何其它内容，再读取两个所需键，不改文件。

两份BK4（offset0、ed000）checksum和结构均通过：0051001d均为1B值00（attr2）；003100a6所在section31的property count=0，确实缺失。CP的be98c6公有代码使用同类header/6B section/6B property查找，但尚未证明当前CP loader绑定的具体数据源就是该公开seed，**不能把公开值写成已观测运行值**。be9130缺项返回-1，不填默认；provider/generator又没有可依赖的失败默认，所以不任选变体，不读真实setting补洞。

```sh
python3 report/cp3006-start/verify_public_seed.py
```

输出只证明公开原件的两键，runtime loader、变体默认和3006成功均false。此成果不是新的ready/空ACK，不触碰原AP/CP状态，也未生成固件照片录像。

## slot1：有条件的真实状态发布与正常观察

索引核对：原descriptor广播b1f3b4把完整word写到`S+16+2*(word>>8)`，getter b1f3ce读取`S+18+2*i`，所以`i=(word>>8)-1`。0301属于getter2/S+1c，周期复制到P+6；0401属于getter3/S+1e，复制到P+a。曾给新调查提供“0301可能是P+a/G+48”的main提示假设有误；随后getter3/74c1f0工作链属于0401，不能作为0301结果。这项错误保留记录并已改正调查分工，不改原bytes或高字节映射。

`0201`经原getter index1写完整u16到P+8，正常observer读取独立T+14；override分支才直接读取P+8，不采用该分支实现成功。T=991daa()在绑定时返回的静态bank：`10fe9c8 + u8[1b15ff4]*210`，两个bank共1056B。

原worker接受真实1cB排队record，执行39e498 callback。在独立状态字M=18b7f68非1/2的已选分支，39e576→99247c→9925b0只将完整P+8写到下一bank+14，完成后39e5a6翻selector，其它bank字节保留。M不是1107178实现mode3，不能混用域；接受队列不等worker执行。prefix/postwork、条件20B消息和completion callback仍有实际副作用，未授权整段no-op。

主会话补上原alias刷新位置。对991daa的全文件ThumbBL扫描只有4da08a、4da24a、b2e616三个候选（旧b2e616作为阳性对照）；前两处原指令均重新写G+44及P+4e40，另刷新G+70=T+1ec、G+98=T+1e8。4da064/68显式装入G=173efe8；4d9f28/36装入P=172fe50，4d9f3c保存r4=P、4d9f76置r8=r4，解决store的寄存器身份。刷新不是依靠修改原指针，也不是每次翻bank便自动更新。

这些代码在原4d9ebc函数内：入口packed数据的高位和低字节分别与*(G+4)的word0及u8(*(G+2c)+1)匹配才走相应处理。P+3d60非0时，9939ea()==1走4da08a，否则1a6a81c+4==0才走4da24a；其它分支保留旧alias或跳过后继。正常receipt另有u8(*(G+2c)+8)及override状态。已定位刷新stores，尚不证明本轮已满足这些gate或已把worker completion准确衔接至正常receipt。

公开配置加载也有更具体入口：Backup_init_cpapp(55dca4)以r0=04000000调用55df9c，后者将该borrowed地址写1a7e85c、验证BK4并建立6B section/property表。它没有在此打开某个文件名；公开seed到该RAM窗口的来源/装载仍未证明。be9130查询缺项返回-1，不填默认。verify_cp.py新增上述真实字节pins、两个原文件bank的摘要/初始completion字节提取；文件初值不当作已执行原初始化后的状态。

独立M的来源及完成回调随后已闭合：原I[1107178]文件初值3，经a96d5c→9a749e映射为0，再由39ee5e周期写M；不是强置M或拿mode3名字代替。实际工作是N=1a6a85c，其root D=1734ed8，通过真实e18B root和c0cB record复制形成相应快照区域；builder用D+8，不是随时读取live P+8。前文抽象G/P入参在实际work内须分别替换为N/D，不能混地址。

实际五word完成记录为`[637075,0,4de191,0,0]`，附加module=1。637074 thunk取记录+8的目标4de191，把module传4de190；后者DMB SY后清1a6a820（执行占用）。正常work在bank发布和postwork后回调；排队失败也会清占用，却未发布bank。占用0不等本次0201完成。其它必选模块、有效配置、完整snapshot/context/prefix/postwork仍需接入，当前尚未新增3006成功服务。

## 有限C核心：实现范围与接口边界

`runtime/analysis/device-models/cp-slot1-publication.c/.h`实现独立核心，尚未链接进当前CP服务或3006传输：

- 每个实例一个实际拥有的工作槽，复制两段已证输入范围；enqueue只排队，execute才消费。额外N/D指针表、完整root及callee对象仍由未来backend负责，不能把这6692B当完整context。
- 维护I→M周期映射；仅接受I=3下完整u16 0201。M=0但I未知/其它值仍拒绝。
- 双bank由调用方提供1056B种子；不自行零填。仅改下一bank+14两字节后翻selector，其它每字节保留。
- prefix/postwork接口均必须存在，没有默认成功handler；未知副作用可明确返回unsupported并保留工作。执行期间允许只读核验，拒绝销毁/取消/重入执行。
- 正常postwork结算后执行已证module1清理等价effect；显式失败清理不建立完整消费。alias读取保留独立字节；本次work审计标识区分旧bank/相同请求值/未完成postwork，标识不是原CP generation判据。
- refresh helper仅复现两条已证gate的局部alias算术，不写原guest指针或sequencer returned；真实packed事件、root/receipt gate来源还需集成验证。

这个组件没有prefix/postwork的生产实现，不得用测试回调冒充真实20B消息、deferred或设备消费；上层合同未齐，所以没有挂进当前3007服务，也没有发送3006 f000。

元数据postwork已另行落实独立[typed发送端实现与所有权合同](METADATA.md)：实际有A0d/8、B3/20、C3/21三种20B格式，包含原cache/失败语义及明确的安全payload释放修复。真实registry投递尚未绑定，故仍不能把它直接当作完整postwork或新增3006成功服务。

当前核验：原固件2.25 libc/pthread/loader的AArch64 `-nostdlib -mno-outline-atomics --no-undefined`独立链接通过；NEEDED只有libc.so.6、libpthread.so.0及ld-linux-aarch64.so.1。C源码SHA256 `d80ea02fb6a811b00847dd2957e6a107a2f48efca8e8a82ab2e9c3c86296c274`，头文件`f260753fab3fdd8b5fb227df9b7fd7933fb9c6bd0f58745d8c9269fd8ed48cde`。独立逐行静态评审在上述C/H范围未发现可确认P0–P3或越界完成声明；没有替代真实hooks或guest验收。

实际C ASan/UBSan与相关资源/原控制传输/source snapshot回归结果：**6 passed、24 subtests passed**（0.68s）。其中新slot1核心为7个case：正常/重复同值请求、缺副作用handler、prefix失败、postwork失败、尺寸/完整u16/模式拒绝、fork、并发/重入保护。测试验证两段快照已独立复制、除目标两字节外全部bank内容不变、原alias/旧bank不等本次完整消费、清理和完成分开，以及执行期间不能销毁/取消。其余17 subtests属于已有CP传输回归，不能都算作新slot1用例。

```sh
cd runtime/analysis
python3 -m pytest test_cp_slot1_publication.py test_cp_sync_resources.py \
  test_cp_background_device.py test_source_snapshot.py -q
```

上述门控没有启动VM、没有调用原CP代码、没有实际消费guest的3006；当前源码仍未将该有限核心接入observer构建/transport。后续须补完整context及真正prefix/postwork，然后和其它必选模块共同验证。

## 其它必选模块的当前边界

0401/getter3的实际work输入与完成项已闭合：4d9b84提交N=1a6a85c，浅拷贝完整c8B/50word指针视图至128b338；仍借用D和资源，不是复制所有指针目标。module3占用1a6a828在入队前置1，原637074→4de190(3)在DMB后清0。入队失败同样清占用，但不执行work或翻bank。

真正0401路径是74ca7a→74c29a→23cef0(W,nextBank)，后者调用24d5c0建立真实资源descriptors，再经77241e/7725b6写nextBank首u16，返回后才翻selector。结果不是固定0401；原某分支可以保留快照D+a，但17929b0/17929b1/179d0b0等gate的有效初始化未证，不能选方便分支。nextBank位于`2003738+selector*19fc`，及其指向资源均不由ROM提供初始化后内容；资源初始化/借用寿命/防重入仍须闭合。未实现0401成功backend。

后续已找到这些gate所属的shadow ID及官方seed第二BK4记录中长度完全相符的资源块，见[公开资源块与装载边界](SHADOWS.md)。但be901c只是长度查询，不是payload复制；primary/secondary表选择及消息更新仍未绑定，不能把公开候选内容当当前RAM或完成判据。

真正0301/getter2的正常位置为root+2950。主会话又找到8c8f30的真实输出首u16写入：来自一个已生成temporary；34ff4c的0301 TBH项0指向3502ee，只有byte1ad4219==0时选择0301并在3509e0写temporary。输入temporary的header又来自2018df8参数对象，尚缺其真实producer/validity及gate生命周期。因此这是有条件的输出写入证据，不是完整0301消费或可用冷模型。两个模块都仍pending，不靠直接写header完成。
