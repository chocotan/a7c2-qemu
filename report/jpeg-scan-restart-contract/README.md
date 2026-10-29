# JPEG SOS模板与restart控制边界

原decoder接受的SOS模板已经查清。encoder向a0/a4写入的常量仍没有已证明的restart位义，因此`NJPEG_GAP_SCAN_RESTART=2`保持，native START仍为NEED_DATA。本目录是公开ALLLANG只读源合同，不执行VM、网络、设备或private/full数据，不改变编码模型的成功判据。

## 已闭合的SOS内容

av-cam.bin raw K30a0e0保存12字节：

```text
00 0c 03 01 00 02 11 03 11 00 3f 00
```

相对于FFDA后的length字段，这是BE16长度12、Ns=3、组件1使用DC/AC表0/0、组件2和3使用1/1、Ss=0、Se=63、Ah/Al=0/0。K2aafe4..2ab030在FFDA分支读取12字节并逐字节匹配，差异进入K2ab140拒绝路径；原字符串为`dgis_jpeg_decode_check_sos`，源文件字符串为`src/dgi_jpeg_decode.c`。这些是原字节和source-family锚点，不是恢复的ELF符号。

这证明decoder要求该扫描头，不证明encoder实际生成这些字节，也不证明entropy后面没有第二个scan。

## FFDD不是寄存器interval的命名证据

marker表K3862c8以marker-c0为索引。FFDA映射到原KVA ffffffc0012aafe4；FFDD映射到ffffffc0012aadd8。FFDD路径跳过DD、调用K2abf54读取BE16 **segment length**，再按该长度移动cursor。它没有读取DRI payload的interval两字节，也没有向MMIO传递restart字段。

原encoder固定调用K2a4098时，w2=1、w3=0。其32位MMIO写入把B+a0.bit0设为w2低位，把B+a4低16位设为w3并保留高16位。K2a4110把B+b0.bit0设为w2低u8是否非零；本路径传1。这些字段仍不能命名为restart开关或interval，也没有来自原P参数的可交付scan/restart字段。

原prefix builder K2ac7a0只生成DQT/DHT/SOF0，没有DRI。原完成K2ace40..2ace54只检查输出头两字节FFDA后再写prefix；它没有执行上述12字节SOS验证或检查RST。因此不能把prefix无DRI作为硬件restart关闭的证明。

## 实现边界与复核

第一个未解释边界仍是K2af7cc调用K2a4098后，a0.bit0/a4.low16在ASIC中的实际行为；b0.bit0也未具名。[现有硬件core](../virtual-jpeg-hardware/jpeg-hardware.h)的baseline/restart=0属于明确的host typed contract，不因这次源调查变成原生寄存器语义。

[source-pins.json](source-pins.json)保存10窗口、2376字节，完整原件身份及K地址映射。K为raw offset，原KVA=ffffffc001000000+K。`test_source.py`独立读回所有摘要、SOS字节和两个marker表项。

```sh
python3 -m pytest -q report/jpeg-scan-restart-contract/test_source.py
```

E1（SOS模板和比较）→F1（decoder扫描头合同）；E2（FFDD表项及长度跳过）→F2（没有interval解析边）；E3（setter、encoder调用、prefix及完成检查）→F3（固定寄存器写已知，restart位义未闭合）。marker parser的Kuna raw-base恢复未能跟入保存原KVA的jump table，该反编译不作分支证据；分支由实际表项和原指令核对。

`whole_branch_closed=false`、`native_capture=false`、`original_consumed=false`，不清除gap2、不发IRQ或成功ACK。
