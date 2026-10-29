# 原CPU像素reader与有界软件JPEG调查

原件`libgstvideo-1.0.so.0`确有CPU逐字节读取YUY2/UYVY/NV12并写AYUV的实现；尚未把这些通用格式reader接到同一CMOS/RC/JPEG capture lease。检查的路径未找到CPU JPEG压缩实现，不能据此认定整份固件不存在软件encoder，也不能把native YC选择为NV12。

范围为公开ALLLANG `menu-root/{usr/lib,system}`只读ELF/原字节与Capstone核查，无执行固件、VM、网络、硬件或private/full。两原件完整身份及8窗口2896B在[source-pins.json](source-pins.json)。本报告是3234/381已冻结代码轮之后的独立源证据，不倒算为该轮测试或拍摄结果。

## 原件CPU像素读取

`libgstvideo-1.0.so.0`为571080B，SHA5c4df2f111f41b3689c23e0a2b7814da3ebac4e93db23e1eb4041531aaadb49d。ELF VA5db58的gst_video_format_get_info选择`93ea0+format*f0`；entry+a0为unpack函数，目标format6的同表名字是AYUV。

| 原格式 | entry VA | unpack VA | even-x标量字节映射 |
|---|---|---|---|
| 4/YUY2 | 94260 | 5cdd8 | A0,A1,A2,A3 → FF,A0,A1,A3; FF,A2,A1,A3 |
| 5/UYVY | 94350 | 5cbb8 | A0,A1,A2,A3 → FF,A1,A0,A2; FF,A3,A0,A2 |
| 23/NV12 | 95430 | 5b7e8 | 两Y样本与相邻Cb/Cr分别组成两个AYUV像素 |

已恢复参数：x2=destination、x3=plane指针数组、x4=stride数组、w5=x、w6=y、w7=pixel count、w1=flags。YUY2的5ce80..5ceb0用单字节ldurb/sturb实现上表；UYVY同样直接按字节操作。

NV12在flag bit1清零时实际寻址：

```text
Y = plane[0] + y*stride[0] + x
C = plane[1] + (y>>1)*stride[1] + (x&~1)
```

5b8b4..5b8e4读取Y0/Y1和C0/C1并复用chroma。这是库内部格式的内容型证据；库包含多种格式，不能仅凭其存在推断camera的实际分配布局。表VA不等于file offset（如94260映射raw84260），必须按ELF PT_LOAD解释。

## 软件压缩候选的实际边界

libmpr的`libjpeg`命中为Sony C++类。检查的get入口26d540/1c4字节搬运元数据并调用accessor，没有在该函数建立raw-pixel压缩循环。`MprIf::EncodeStill(EncodeStillParam*)`2c8cd8恰好只有`mov w0,#0; ret`（8B）；它的返回0不能证明实际编码完成。该结论不推广到所有MPR方法。

339个ELF动态符号表的所选format/frame API导入查询只命中libgstpbutils；没有直接gst_video_converter_new/frame importer。间接调用未穷尽，不能据此认定这些CPU循环未被使用。

360个非symlink文件（189754536B）的精确字节signature查询未命中IJG常见版权/错误信息、jpeg_CreateCompress/Decompress、jpeg_start_compress、jpeg_write/read_scanlines、JPEGLIB/jpeglib/JFIF。标准IJG亮度量化16B前缀只在av-cam raw38eabc命中；常量并不证明software compressor。stripped、自定义、packed或动态实现仍未排除。此前三候选ES read/message库及Sony service库的metadata-only负例另保留在`runtime/analysis/scratch/original-software-codec-triage.json`，不因名字中codec/encoder就重用它们。

E1（表/回调/实际字节loop）→F1（原件有通用CPU格式reader）；E2（有限metadata/stub检查）→F2（这些候选未证明压缩）；E3（有界签名/直接导入查询）→F3（没有找到可接capture的现成路径，非全局不存在证明）。下一步仍需capture lease的实际格式绑定或original0 producer；未接之前保留native JPEG NEED_DATA/ENODATA、gap63、capture=false。
