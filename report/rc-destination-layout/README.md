# RC目标记录与DMA提交合同

本成果沿公开 `av-cam.bin` 的原JPEG转换分支，把RC provider之后的目标记录构造和DMA寄存器提交追到可核对字段。它不证明ASIC里的Y/Cb/Cr顺序、plane数量、chroma偏移、DMA lease或真实像素消费。

原件为 `runtime/analysis/menu-root/system/av-cam.bin`，13,797,088字节，SHA-256为 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`。K地址是raw文件偏移，KVA为raw+`ffffffc001000000`，不使用CP映射。

复核命令：

```sh
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib -q \
  report/rc-destination-layout/test_source.py
```

已闭合的原始路径是：

```text
原JPEG转换对象的目标描述符
  -> K2d7958 校验/复制到 J+98
  -> K2d86fc 准备目标记录
  -> K2cdc94 构造记录
  -> K2d4588 提交三组DMA字段
```

在selector=0的原JPEG分支中，目标压缩和位深均由原代码写入0，随后通过 `K63128 SetYcCompress` 的0分支进入RC请求；该selector来源仅限这条原JPEG转换分支，不能推广到其他RC调用者。

选定目标记录的具体字段为：

| 字段 | 原值/来源 |
|---|---|
| `M+08` | `P=A+2*((y+Vy)*W+x+Vx)`，A为目标转换结果 |
| `M+10` | `(P>>24)&0xffffff00` |
| `M+14` | `2*w` |
| `M+18` | `2*(W-w)` |
| `M+1c` | `(h-1)&0xffff` |

因此 `M+14+M+18=2*W`，这是地址步进/宽度关系，不能命名成Y、Cb或Cr的布局。DMA提交把这些字段分别写到通道寄存器`+18/+20/+24/+28/+2c`；辅助记录还写`+30/+34/+50/+54/+58/+5c/+64/+68/+6c`。通道基址来自原表，但尚未把表项绑定到实际虚拟帧或lease。

`J+98`由buffer-range list构成，不能拿其他路径的selector或descriptor word值来猜plane数量。`J+104`在某个输入为0时由原helper早退、不写出，因此也不补零。

下一步若继续，只能追 `K2c9f34` 的模式记录来源、`K2cdc94` 的目标记录解释和 `K2d4588` 对应硬件通道的实际格式定义；在这些合同闭合前，native JPEG仍应保持 `NEED_DATA`，不把宿主RGB或假定的YUYV/UYVY写入原固件路径。

状态：`native_pixel_layout_known=false`、`guest_pixel_consumed=false`、`capture_verified=false`。
