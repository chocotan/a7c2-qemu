# 模块2正常完成字的光圈状态来源

`H+2`的公开字段名为`uc_IrisInitComp`；三bank stride为`0x520`，不是十进制520。字段读取、初始化计算与bank复制/发布规则已静态闭合，**profile2实际工作完成后的持续更新、发布链仍未闭合**，不能强置该字段为1以放行302c。主会话独立核验[20个原始窗口](cp-slot2-iris-status-source-pins.json)及字段descriptor，`302c/capture`继续false。

## 字段与当前bank

CPVA df2938的四word descriptor为`{f78208,1,0,1717512}`，字符串f78208为`uc_IrisInitComp`；H0+3为相邻`uc_IrisInitEMG`。描述项不是函数指针。

a76188读取profile=`**(u32**)19f9250`，默认返回H0=`1717510`。仅profile2返回`H0 + u8[1b1a0a3]*0x520`；getter自身不做index取模或边界检查。三个合法bank为1717510、1717a30、1717f50。

a75d40返回ROM df27f8，其四word为`[2,0,0,2]`；a7abc4将该指针安装到19f9250。这证明该初始化事件后的指针来源，不能冒充当前RAM指针、index或bank内容已读回，也不能将profile称为scheduler core ID。

## 可以实现的有限生命周期

| 源操作 | 精确效果 |
|---|---|
| a75d8e构造 | a75dec只清H0前8B；完整520B复制到H1/H2，最后index0。其余H0字节不因此变成已知零 |
| a76494 | profile2返回next=`(index+1)%3`，其它返回H0 |
| a76506 | profile2将当前bank完整复制到下一bank |
| a7655a | profile2先发布index=`(index+1)%3`，再将新当前复制到随后一bank |
| a780e6(source) | 先index0，再复制source前520B到H0，保留H1/H2 |
| 32b858..886 | 调用getter，读所选H+2，再写working C+10aa |

复制必须继承每字节known mask；构造只证明三个H+2为0，不能为整bank未知字节补零。复制和切bank也不证明产生了新光圈操作。模拟器记录的generation应标为自己的审计元数据，不称原固件字段。

## 实际源计算

a7ce70调用40076c(O)，O=`10e8a88`，之后a780e6(O+4)将源对象O+6发布成H0+2。实际计算store在400824。

令S=`u32[1a040ac]`，T=`u8[1a0410c]`，L0/L1为1b1a167/168，R为a93716的实际返回。三个谓词：A为`R==1 && S∈{6,7}`；B为`R==1 && S∈{14,fe,ff}`；D为`T==0 && R==0 && S∈{0,f2,f4}`。源函数先按分支清理两个latch，再按调用顺序计算：A或B成立写O+6=1，否则写`D | ((L0|L1)!=0)`。

重复谓词调用之间可能状态变化，不能把多次实际读取合并为一个未经证明的旧快照。R也不是一个ACK：它检查a48662、状态区间和S+4c；a48662从19edf80/84取GPIO bank/pin，调用bf7838读取f101d000/d010/d040加bank<<12的MMIO位，再异或1。selector赋值a4851a/a48532来自be92ec配置。当前没有该配置返回值、GPIO电平及相应操作完成事件的运行证据；BSS或默认GPIO不能替代R。

当前 `cp-iris-status` 三 bank 模型宿主回归通过 **25 passed**，使用严格 C11、ASan/UBSan。测试覆盖 profile 2 的 stride `0x520` 选择、先发布后复制、未知字段 mask、H+2 采样、profile 非2 no-op、fork/重入/别名和溢出拒绝。该回归只验证字段/银行数据流，不验证 GPIO/MMIO、实际光圈完成、原 CP 调度或 capture。

## 完成候选与尚缺的profile2更新

明确的下层候选40bcdc由a94dcc..dd6→a946fe注册callback。它要求状态byte1a040ac为11，且计数byte1b1ac6c不大于1b1ac6d；40bd52/5e据a909b0读取的1a03ad0将S写7或6。该写入本身未证明计数来自完成数据消费。

3fc844有严格profile分派。公开profile原始2/第二word0时，不能借profile1的3fc09c→3fc352路径宣称O+6更新。40076c目前只定位到a7ce96这个直接调用，属于初始化发布。下一源边是a946fe真实完成callback派发与两计数的producer，以及profile2完成后S/latch如何再次进入O+6或下一H bank并发布为当前。

## 正常刷新时效

89d874→8a6d8a不是所有normal路径都走：通常由`u32[*(SB+c)+b94]` bit2控制，非零跳过；1ad4275为负时低7位1强制跳过、2允许复制、3另依赖r4+3c与1ad4633变化。

8a6d8a只复制f4cB，恢复目的+a1f；复制范围不包含+10aa。因此“中央工作对象复制发生”不能代替状态采样发生。必须分别记录：是否执行复制、32b884/886是否采样，以及该样本对应的实际bank历史。

0323/032c的临时完成字助手只能依据真实known命令、status和prior word计算候选。它不写G+10/P+2950，也不证明其它模块或中央状态完成。0302有额外字段分支，继续保持不支持。
