# AVC SPS网格：Q语义已证，P/B别名仍缺

实际CPU SPS writer及其宽高字段语法已找到。对该函数第二参数Q，可以按H.264语法解释coded grid；尚未把Q绑定到由P准备的AVC命令块B/模板T，因此**不把P16/P18或B9c0/9c4直接解释成图像像素尺寸**。

范围为公开Imola2只读静态证据，无执行固件/VM/网络/硬件/privatefull。8个RAM0窗口4360B和完整原件身份见[source-pins.json](source-pins.json)。首轮代理超限的部分结果被保留，续轮补交以下边界；没有因此填默认值或增加猜测的geometry resolver。

## 实际SPS函数与语法

SPS writer为80101a68。Kuna恢复的801044f4构造把vptr80240580装入header-controller+6c的embedded writer；该表+1c为80101a68。80105dec通过该槽调用，复制产生的字节并记录NAL type7；writer自身也把literal7交80101008。虚表/构造相关窗口与writer原字已列pin。

令Q为writer第二参数，80101aa0..ab8建立s4=Q+8，后续实际operand因此可统一定位：

| Q字段 | 写出位置 | H.264语法 |
|---|---|---|
| u32[Q+14]&3ff | 80101bc0，delay slot1bc4 | UE pic_width_in_mbs_minus1 |
| (u32[Q+14]>>10)&1ff | 80101bd0，delay slot1bd4 | UE pic_height_in_map_units_minus1 |
| (u32[Q+14]>>19)&1 | 80101be4，delay slot1be8 | 一bit frame_mbs_only_flag |

该次序位于profile/constraint/level、SPS ID、profile extension、frame-number/POC、reference count和gaps flag之后。UE链80101318→80101514→80101038先由801014e4计算floor(log2(value+1))，再写zero prefix、leading1与剩余位；不是仅凭字段形状命名。

仅对Q，令f=Q14.bit19：

```text
coded_width  = 16 * ((u32[Q+14]&3ff)+1)
coded_height = 16 * (2-f) * (((u32[Q+14]>>10)&1ff)+1)
```

这不是logical cropped image的尺寸。Q14.bit20为条件MBAFF，Q18.bit30为crop-present；crop UE值来自left=Q14>>22、right=Q18&3ff、top=(Q18>>10)&3ff、bottom=(Q18>>20)&3ff。配置实值、chroma/crop unit及其到拍摄buffer的绑定未在本轮建立。

## P/T侧确切代数保持独立

令x=u16[P+16]、y=u16[P+18]、M=(u32[C+8444]==1)：

```text
T9c0 = x+1             [u32，范围1..65536]
T9c4 = y+1
T14.low10 = x&3ff

t = ((y+1)>>1)-1
if !M && (T14.bit19 || T620.bit20): t=y
T14.bits10..18 = t&1ff
```

80161568/570实际为s0=P+14时的lhu[s0+2/+4]，进入同一setter80163d78。完整u32 store、masked SPS-style字段和条件halving不能混为同一个数。尤其不能给full stores做u16 wrap，或忽略mask与field/frame条件。

## 最先未闭合的别名

header准备80105c68获得L=u32[F+c]、A=u32[L+c4]、Q=u32[A]，经80105dbc→80105dec传给embedded SPS writer。尚未定位将此A[0]设成已准备B或T的那条store。**Q=B/T未证**，所以Q的标准SPS网格语义不能跨到P/B的actual image dimensions。

E1（NAL7 writer/bit syntax）→F1（Q的SPS fields）；E2（P参数load与setter）→F2（独立masked/full-store公式）；E3（Q的选取链及缺store）→F3（不跨域推单位）。后续若正向闭合alias，仍需分开coded padding与logical crop，并结合actual original0 byte layout；本轮不生成或编码帧。`capture_verified=false`、gap63。
