# VBB输入配置：同址写配置不等于已知ready或stream模式

已找到bf068200/600/400这些nonzero gate同址的参数配置writer，闭合normalizer两个mode的直接输入来源。**原图像地址的读/写方向仍未知，live/on-chip替代路径也未正向建立。** 不能由gate=0推断streaming，也不能断言所有硬件模式都必须使用Y/C memory。

范围为公开Imola2只读原字节/静态方法核对，无MCU/系统VM、网络、设备或private/full。原代理10个定界窗口7908B，主会话另核完整160B byte-fill helper；11窗口8068B（含重叠）和完整原件身份见[source-pins.json](source-pins.json)。本报告是3249/381冻结轮后的独立源补充，不倒算测试或native执行。

## 三个完整配置方法

core0 context C的vptr8023c490，+14=801be154配置，+18=801be358 launch。配置方法的真实顺序：

```text
801be154(C,I,G,K)
  801bf330(C,I,G)           参数clamp
  C.byte1c=I.byte2
  C.byte1d=I.byte3
  801bf3e8(C+4,I,G,K)       硬件配置
  若u32[C+10]非零：80079174(u32[C+10], I+24)
```

I/G/K是函数参数的中性标签，不是已恢复source type。normalizer address mode来自I2、auxiliary mode来自I3；数字0/1/9等仍未获pixel-format名称。数据写到C并不证明随后的硬件配置或帧已经应用。

完整clamp801bf330..801bf3e8把u16[I+4]夹到1..21ch，u16[G]夹到1..200h，u32[I+10] low10夹到1..21ch，下一两bit夹到0..2。单位未命名，不把这些阈值猜作像素或macroblock尺寸。

## Gate寄存器的实际writer

完整801bf3e8..801bfd98令H=C+4，与稍后801c0790使用的hardware context相同：

| 写入位置 | 源支持的赋值 |
|---|---|
| H.byte0 | I.byte0==1 |
| H.byte1 | I.bytee&f |
| H.byte2 | I.byte9 |
| bf068028 | I.byte0==1时184h，否则80184h |
| bf068200 | (u32[I+c]>>24)&f，即I.bytef&f |
| bf068600 | (I.byte9&3) \| ((I.bytef&3)<<4) |
| bf068400 | 参数组合的control word，bit2置位 |
| bf068800 | 条件写入由I4、G、context shift等组合的word |

关键store在801bfa18、801bfaf0、801bfb54，optional block在801bfc50。局部构造结构在sp+10被80067f08以value0、size44h填充；主会话核过该完整helper的SB/SH/SW byte-fill与return-delay，因此不把未初始化stack误当reserved0。

具名assert与同一函数参数绑定：802160d4为`init_param.h_sh_ratio <= MAX_SH_RATIO_NUM`、80216100为对应v_sh_ratio，指向`.../ctrl/video/bb/vbb_drv/imola_ft_drv.h`。检查直接使用I.bytec/I.byted，两者须小于3。它们没有给ReadIF/WriteIF、memory/live input或source-port命名。

## Read-side语义仍未定义

这个configuration方法在801bf45c..484先要求当前bf068200/600/400的load非零，optional段也检查bf068800。launch方法801c0790有同型检查。主会话独立确认是实际MMIO内容读取，而不是只判一个register pointer非NULL，例如：

```text
801bf45c LUI a2,bf07
801bf460 LW  a2,-7e00(a2)  => read bf068200
801bf464 BEQZ a2,...
```

同址参数writer证明write-side参与配置，但**没有证明read和write具有相同硬件意义**。它可能包含status/config混合、read/write alias或硬件更新。初始nonzero的建立、各bit含义和硬件行为仍未解释，不能把它命名为纯bufferReady，也不能以软件写入配置为由假定读回就是该值。

I.byte0==1会改变control bit19与optional块参与，I.byte9影响配置及work.bytec；这两个selector都没有source-supported live-vs-memory解释。基类/派生AVC差异也尚未被证明是input mode选择。

## 当前实现边界

W0/W4的launch路径只把值写到bf068214/bf06860c，没有CPU image-pointer dereference来判定输入、输出或in-place。后续engine参数block也未给出方向/pitch/packing。当前没有可据此移除未知memory layout依赖的已支持mode，同时不证明hardware不存在另一种能力。

E1（vptr/config sequence）→F1（mode输入来源）；E2（完整参数writer）→F2（配置参与）；E3（真实MMIO reads）→F3（nonzero检查存在，语义仍待spec/同lease观察）。有限数值转换已在[normalizer](../imola-vbb-normalize/README.md)实现；它不承诺此处硬件配置、live输入或像素执行。后续需要这些exact registers的规范，或同一实际buffer lease贯穿硬件消费的证据。`actual_origin_pixels_consumed=false`、gap63、capture=false。
