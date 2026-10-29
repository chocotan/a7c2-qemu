# LIF gate输入：公开属性与初始配置投影

两个enable输入已有正向源绑定。FLAGA在公开CP initial stage的属性000d003a中为ff（bit0=1）；FLAGB在所选初始配置传播后为0。因此可以建立这个有限owned初始化片段，但不能认定原worker调用时gate为零，六字段published zeros仍未通过。

范围为公开CP/ALLLANG只读静态核对；无系统VM、网络、硬件、物理SD或private/full。没有新增默认值、ready或ACK，也没有改变已测运行时代码。

## FLAGA的实际公开payload

完整属性ID000d003a属于section000d。CP初始stage为ALLLANG[ed000:]，1419512字节，SHA a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977。

| 项目 | 原值 |
|---|---|
| section entry | stage+014e；count108，first4238 |
| property entry | stage+78e2，字节08009ad503ff |
| attribute | 0008 |
| length header | stage+3d59a，LE16=256 |
| payload | stage+3d59c，ALLLANG+12a59c，256字节 |
| payload SHA | b3dcc9455b88ff528026e892fab01a54c0c1ce80e4ccb9fd370b71d02a5c4c0c |
| payload+b8 | ff |

两个表的相同index **0x29（十进制41）** 给出绑定：u32[1106a5c+0x29*4]=1ac029c，u32[1106b98+0x29*4]=000d003a。十进制29则对应1abfc9c/000d001d，不能混用。a75b68登记full ID、callback a75d11和context1ac029c；55bf60→be9130的初始读取通过be917e把repository payload复制到context。更新be9e0c按完整ID匹配后调用a75d10，按事件实际长度复制。回调没有把长度硬编码256；256来自此属性的真实元数据。a75c54→55c44c则是反向写回，不是初始化读取。

3e6850读base1ac029c+b8，所以这个公开初始payload给出FLAGA bit0=1。后续property事件的值与发生历史尚未闭合。

## FLAGB的独立配置子根

b2a82a(out)调用b2a374(1,0,0,4ce699,0,0,1,0,out)。原CFG中b2a7c8/ca比较并选择4ce699分支，b2a7f8设置r3=2；经b2a51c到b2a540 STRD，写out+18=0、**out+1c=2**。该选路不经过1a53158条件分支；后续字段写不覆盖+1c，尾helper只收到out+74。

令S=172fe50，初始配置写在S+1144=1730f94。b2e686复制304字节到1731298，b2e694复制同体到1730c88。bank3=S+e18=1730c68，因此getter的bank3+64c=17312b4，恰好是1731298+1c。

99b86e读取这个u32并返回(value==0)，实际初始word2得到0。3a9d48调用getter，3a9d4c把返回值交给a4dfc6，后者STRB到169df18+100=169e018。只有执行这个collector投影后FLAGB才成为0，初始化memcpy本身没有直接写该字节。

该字段超出d64参数根副本，不可用P的同名偏移代替。实际collector入口为3a91e4；旧Kuna标出的3a9b00是函数内部循环指令，不能据其名称推断入口。

## 不可跨越的时间边界

运行期b2ee12再次复制1730f94的304字节到1731298，明确可覆盖这个word。此前已见99286a/992bc8条件调用和pointer-view复制；初始view、该次collector、40c3be→3e6850及worker138908的完整顺序仍未闭合。初始FLAGB0不能沿用为任意后续默认值。

E1（同stage真实属性、表配对及读回调）→F1（FLAGA初始来源）；E2（精确常量分支、copy、bank3和STRB）→F2（FLAGB有限传播）；E3（运行期重copy）→F3（worker时刻历史仍缺）。10窗口4180字节和公开payload身份在[source-pins.json](source-pins.json)中，主会话独立重读核对。仅所述owned初始snapshot的enable conjunction为假，不发布六字段零或拍摄成功。
