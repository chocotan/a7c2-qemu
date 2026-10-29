# default/type0：独立ISP wrapper与真实参数复制

原default queue805700f9现在有独立正向binding：先经ISP wrapper，再按原state/subtype与byte88条件到common receiver。packet+10→98B source copy已找到，不再以“同ABI”代替来源。**未观察runtime状态、分支值、完整extent/lease或硬件消费，gap63/capture=false。**

公开av-cam.bin只读，10个新窗口3692B及完整身份见[source-pins.json](source-pins.json)。K为raw，KVA=ffffffc001000000+K；无固件执行、系统VM、网络、设备或private/full。源增量独立于3249/381冻结轮。

## zero constructor实际选择

A58cc..A59c4 caller传type0与destination805700fa−1=805700f9；shared constructor保存C+8/C+c，沿既有recv/dispatcher。不能由type1继承此选择。

A6264..A6468完整normal constructor令G为this，构造Z=G+116a98（139894）、H=G+116e98（A71a8）与T=G+1164e8（193c88）。A63fc..A6404检测type0，zero到A642c调用12c968(G,Z)保存Z；非zero才选H。

Z安装vptr358b28，Z+8为context，Z+338保存H。RTTI为sfmc_enc::sfmc_enc_ext_isp_if，vtable+10/raw358b38目标139954。因此type0有真实ISP wrapper，不是type1的receiver+690换个queue名。

## subtype与实际source copy

139954对CID2003到13a0fc，保留其MID8201/CID8003/200d的其他特殊分支。MID0201、u32[packet+2c]=210、u16[packet+a]<=4时按3589f0表分派：0→13d8b0，1→13e8e4，2→H virtual+10，3→13ed88，4→13efd8。

subtype0先copy packet的30h/48B到temporary，再附原w2/w3到temporary+30/+34，故+10指针/+2c command都被实际保留。13d8b0→13d8cc按原state dispatch；state2表row3591c8={140304,14030c,140324}，action14030c调用13bb98。state12也可经14044c选此action，但没有观察真实state。

13bbac从temporary+10取完整指针。非零时13bbc8/13bbd8分别从该源copy98h到Z+120和Z+1b8；13bbdc读取**原source+88**，非零调用13dfa0、zero调用13dd50，各传第一snapshot的stack copy。随后13bc18..2c转交temporary到H virtual+10，并恢复原w2/w3。

没有把source byte88、state2或state12设成默认值，也不把两次copy视作frame已编码。

## owner与两个common receiver

A6438..48调用Z virtual+48，传入T；13a5c4将T存Z+10并forward给H virtual+48=169014。后者的177838将T存(H+18)+20，16916c将T存(H+690)+20。T的constructor RTTI为sfmc_enc::sfmc_enc_timing_normal；这是对象关系，不是实际hardware完成。

因此common H的既有byte88选择也可用于type0 wrapper之后：nonzero到H+690/169174，zero到H+18（17774c构造、handler177840）。zero路径0201/210/subtype0的table367cd0选1779a0：先copy28h header，177a04从相同input+10取源，177a18 copy98h到receiver+50，并重写header+30/+38为自有snapshot/长度。保留两种选择，不将零case强行归到169174。

## 与已证路径的关系

[原dispatcher转换](../native-video-pointer-conversion/README.md)的local bypass、first-u64/a8aa8 bypass、metadata-dependent parameter byte67 clear仍有效。[包坐标](../native-video-packet-coordinates/README.md)给出MPR fixed-area双地址与48B→CMD+8；本篇闭合default wrapper的实际读/copy，不认证原运行中的同一个lease。

E1（type0 constructor/selection）→F1（default queue的独立Z）；E2（CID/MID/subtype/state row）→F2（条件action）；E3（packet10解引用copy）→F3（source字段到snapshot）；E4（registration与common receivers）→F4（owner及两种后继）。所有runtime值、全98B安全跨度、生命周期、SDS/frame identity、ES字节与最终原文件输出仍另验；不新增ACK、ready、IRQ或独立host媒体。
