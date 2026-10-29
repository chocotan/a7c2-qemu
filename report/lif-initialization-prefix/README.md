# Init_LIF完整前缀：尚无M/C初始化值，先清零再绑定的P未闭合

检查注册之前的完整前缀后，`M_init_source_closed=false`、`C_init_source_closed=false`。没有可实现的M/C默认值事件；也不能声称整条前缀不改M/C。已知register-only尾部结论不变，见[原ADJ报告](../cp-adj-initialization-contract/README.md)。

本次公开CP只读，无固件执行、系统VM、设备或私有配置。[8个新窗口1090B](source-pins.json)不重复旧4pin216B；新数据不倒算3249/381冻结轮或旧VM。

## 完整入口与属性注册

`[a48f02,a48f6c)`共106B/39条指令/9次调用，依次为40c25c、a98a08、a98a6c、a98f06、989d4a、61ed00、989d5c、a98a20、a98a38。这里的61ed00只清stack 74h。三个Boolean直接目标1a042d0/d4/e4，其他已确定setter目标1107180与mode1的1a03a1c；这些不覆盖M/C，但尚有间接调用。

`[a48ba2,a48c08)`完整102B/32条指令，循环offset0/4/8向be9d98注册3个ID/callback/context，handles写19edfb0/b4/b8，随后55bf60(110208c,110207c)预取：

| ID | context |
|---|---|
| 01250006 | 1211300 |
| 01250005 | 1fd87e0 |
| 0125000a | 1211400 |

callback pointer为a48c09，Thumb代码a48c08..10复制event payload到context。这里未出现M/C值或给19ee17c pointee的默认数据。

40c268→a93694→a48472的完整392B读取属性word，经be92ec返回后写19edf60..19edfa4及1101fc4/1101ffc表项。be92ec完整78B执行lookup/长度4检查/读取，否则返回0；这个zero只提供给上述确定目标，不是M/C默认。

## 不能倒用后发生的绑定

完整直接caller40c25c..40c380为292B/96条指令/33次BL；其全部transitive callees未闭合。关键顺序：

```text
40c2e8 → a91334 → a913d2
    a91450: P=u32[1a03cdc]
    P==0时跳过
    a91478: 61ed00(P,44h)
    之后clear [P+139h,P+1bbh)、[P+1c3h,P+1ffh)
...
40c30a → a901fc → 3e164c
    后来才设置1a03cdc为0/1fd87e0
```

**清零时P的既往来源未知。** 不能设P=1b18330来获得M/C0，也不能把较晚的0/1fd87e0绑定搬到前面，断言早期clear不相交。

首次记录的另一边界是a48f54→989d5c，r0=18aeb8c、r1=sp，helper解对象/vtable+1c；其公开初始化路径已在后继二闭合为98cf9e getter，不产生M/C值。当前对象历史仍未知。紧邻下一模块为4b6d62/4b6d94→b0b202→236bb8（Init_CAIF），也未建立紧耦合ADJ default loader。

## 公有属性的独立内容核对

主会话复用已有`cp3006-start/verify_public_seed.py`的认证与两bank解析，读取同一ALLLANG seed，不写parser或隐式fallback。seed SHA3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47，两bank checksum通过。

bank0这三key均不存在（section count0）；仅ed000起始、在显式CP_INITIAL_STAGE模型中使用的stage有：

| ID | 字节 / attr | seed file offset | payload SHA256 |
|---|---|---|---|
| 01250005 | 1024 / 8 | 1448832 | 5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef |
| 01250006 | 256 / 8 | 1449860 | 9814ef4bd1a406fdee481bc1d47f8c616030922d52d7b5f02747fe61a0401d66 |
| 0125000a | 32 / 0 | 1450216 | 66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925 |

01250005/0a的原payload是零内容；这只属于这两个显式属性的字节，不是M/C默认、当前LIF 600B、history或publication。05的实际长度为1024，不能按一个600B getter名称截断后宣称格式等价。06的profile已由既有stage owner处理；此次没有给owner增加无人消费的copy或提升data-ready。

E1（完整前缀）→F1（已确定direct目标不相交，不推广未知callee）；E2（注册表/lookup）→F2（属性源context，但非M/C值）；E3（先clear后bind）→F3（必须查历史P，不搬运时序）。以下是后续两个独立源任务与主会话定界核对；仍不是“没搜到writer所以默认零”。

## 后继一：有限返回域不是oldP历史

3e164c..3e1754完整264B/90条指令/12基本块，正常返回仅为0或1fd87e0。它不接受/发布任意指针：保存完整r0到19edfcc，r1/r2到19edfc4/c8，r3低两byte到1b18331/32；完整r0>=88b8h为失败路径。否则取property01250005长度H，诊断signed H>-1后仍作unsigned H>=r0；不能将负sentinel测试误当提前return。

成功路径设置r4=1fd87e0，调用3e2060/3e22bc，清19edf28，再经过可选indexed loop，最后统一return r4。**3e164c自身不写P**；a901fc读取源word df6470，供给(值,440h,220h,e15h)，a90216调用后由a90222写P、a9022c写1a03ab0。df6470原文件值为200h，仅是file initializer，不是live readback。

额外边界在3e1746：`u32[19ee00c+4*i] = u32[19edee4] + i*u32[deeb5c] (mod2^32)`，0<=i<u32[deeb54]。i=5734h时目标恰为P；本轮没有建立runtime count bound。文件中的count是10h，不因此消除条件writer。constant-address scan得到209个paired materializations，其中208先read、a90222明确store；它不覆盖computed aliases或所有间接入口，不能以scan count断言all-writer completeness。

在**另行证明oldP∈{0,1fd87e0}**的条件下，0分支skip，非零的3段clear为1fd87e0..1fd8824、1fd8919..1fd899b、1fd89a3..1fd89df，确定不覆盖M/C；P+10e..115的scalar clear也不相交。但无条件oldP domain仍未知，尤其40c2e8 clear先于mode1下的40c30a publisher。新6窗口828B固定此局部值域，不宣称构造调用顺序已观察。

## 后继二：vtable+1c是参数getter

公开初始化路径现在正向闭合为a48f54→989d5c→98cf9e。989d4a返回wrapper地址18aeb8c；98a4b2调用98bcb4，后者固定返回静态地址18aee1c，98a4c2将其写到wrapper。fff0d0/d4/d8的constructor pointers为98a4b3/98af81/98cc7f；98cc7e把对象18aee1c交给98bcbe，在98bcd8设置vptr=de98a0，其+1c word=0098cf9f。所检查基类vptr deafcc的该槽也相同，不假造三个variant目标。

989d5c正常路径完整10B为`19b100680268d2691047`，检查r1非空后读wrapper/vptr/+1c并尾跳。当前r1=SP。98cf9e..98cfd4完整54B/19条指令：若12110e0/1不为ff，更新this+550/54f；随后唯一copy primitive61e60c从this+54c复制74h到输出，return0。在该对象绑定下只写18af36c/18af36b与caller stack，copy源18af368..18af3dc。**这个具体getter不初始化M/C。** 名称仅来自编译assert字符串`Camera::Imager::C_Imager::GetInitParam(...)`。

构造器局部写this+558=0、this+590=044aa200，故只在额外证明构造后未改写时，输出stack+c/44有这些值。当前wrapper/vptr/override/成员历史未闭合；不能把constructor snapshot当postStartup值。新8窗口1448B及真实copy helper固定该结论。

## 主会话核LENS_DATA两个callee

3e2060..3e20e6完整134B是`InitializeLensDataArea`路径：3e2140取区域地址/长度，经4项mapping table与5feb94地址filter；要求实际长度>=调用所需长度后61ed00清区域。3e22bc..3e2394完整216B填写19eded4的一组area offsets与AXIRAM descriptor，不直接写M/C。这里又取property，不借任意“邻近M/C所以会清零”的猜测。

3e2140..3e21dc完整156B读取**00fa0112作为u64地址、00fa00ab作为u64长度**；不是00fa0113。已有认证reader独立核得ed000 stage值分别0808000500h与b980h；bank0二者都是ffffffffffffffff。mapping source tables CEE8B0/CEEDB0对上述显式stage输入给出逻辑地址08000500h和长度b980h；**5feb94并非无条件converter**，它调用611ddc，只有query返回0且输出byte bit2=1时保留该地址，否则返回0。故`[08000500,0800be80)`只是filter允许时的候选clear范围，与M/C分离；未证明runtime属性/表/query或实际clear发生。00fa0149/14a在两bank分别为f6000000h/1000h，是AXIRAM声明，不能授权host dereference。00fa0113在这里只是未使用的邻项，不能当成size。

这些7窗口850B含完整helpers/filter、file count初值与两张4项mapping表。[source-pins.json](source-pins.json)保留原8窗口与3组后继，共29窗口4216B（含重叠），各阶段独立；原CP从未执行。M/C实际值、oldP历史、全部transitive calls与实际worker publication仍未闭合，3003数据0/4与capture=false保持。没有添加无人消费的copy/helper/default，也没有新增packet或ready shortcut。

