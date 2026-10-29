# YC分量消费：CPU候选与SA提交边界

本次公开原件调查没有闭合同一RC/JPEG缓冲的CPU分量解包。已核实SA提交请求的原参数与程序payload身份；SA指令语义、分量顺序及同一SDS/lease绑定仍未知。因此不能据此选择YUYV、NV12、plane顺序或chroma布局，native JPEG START继续返回NEED_DATA。

范围为本机只读公开ALLLANG原件，不使用真机、物理SD、private/full dump、网络或VM。该目录只保存源合同和否定结论，不新增像素模型或成功回执。原始固件不随交付复制。

## 实际路径与参数

原`av-cam.bin`的K短地址是raw offset；实际内核VA为`ffffffc001000000 + K`。

| 源步骤 | 已核实内容 | 实现边界 |
|---|---|---|
| K1d44ac起 | ImageSizeInfo复制0x48字节到callback记录C+20；尺寸到C+b4/b8，canvas宽到C+bc | 描述符和尺寸传递，不是像素解包 |
| K1d4bf4 → 1d4ca4 → 1d596c | 构造make-MMU请求，提交目标930101 | 地址转换请求 |
| K1d52e4 → 1d5610 → 1d596c | 构造SA计算参数与AA请求，提交目标930101 | SA程序输入，没有CPU分量读取循环 |

P是由C+98转换得到的参数缓冲。源实际写入：

| 参数字段 | 值 |
|---|---|
| P+00 | 0x1564e |
| P+04、P+08 | u32[C+b4]、u32[C+b8] |
| P+0c | 2*u32[C+bc] |
| P+10、P+14 | 1、0；未恢复其格式含义 |
| P+20、P+24 | 转换后的C+70、C+80地址，分别右移两位 |

关键原字节：K1d5564..5570为`2800a052 c8c98a72 280300b9`，写程序号1564e；K1d5590的`297f0229`写1/0；K1d5598的`2a2f0429`写两个地址字。

SA包确有`SA_NV12_0x02`与`NV12CONV0x02`标签。标签及payload身份不能证明该ASIC程序的lane操作，也没有证明其输入就是原RC/JPEG的同一缓冲实例。

## CPU候选的确定结果

`libObj.so`的GRM_fbrmInitializeYUV、TerminateYUV、PrepareUpdateYUV、UpdateYUV、FillrectYUV和RectblitYUV入口位于ELF VA f9014、f901c、f903c、f904c、f9054、f905c。各入口都是`00008052 c0035fd6`，即`mov w0,#0; ret`。这些函数没有消费像素或调用下游renderer。该结论来自实际函数体；不推广成公开固件内不存在其他CPU消费者。

## 证据与复核

[source-pins.json](source-pins.json)保存3份完整资产身份以及6个半开窗口，共7144字节。主会话已独立读回全部窗口、长度和SHA-256，与调查结果一致。窗口不含运行态RAM或假设的零数据。

从成果根目录可只读复核：

```sh
python3 - <<'PY'
from pathlib import Path
import hashlib, json
base = Path('runtime/analysis/menu-root')
pins = json.loads(Path('report/yc-cpu-consumer-boundary/source-pins.json').read_text())
images = {}
for row in pins['artifacts']:
    b = (base / row['path']).read_bytes()
    assert len(b) == row['size']
    assert hashlib.sha256(b).hexdigest() == row['sha256']
    images[row['path']] = b
for row in pins['windows']:
    b = images[row['artifact']][row['file_offset']:row['file_offset'] + row['length']]
    assert len(b) == row['length']
    assert hashlib.sha256(b).hexdigest() == row['sha256']
assert len(pins['windows']) == pins['window_count']
assert sum(r['length'] for r in pins['windows']) == pins['window_bytes']
print('source windows verified; pixel layout remains unknown')
PY
```

E1（GRM原函数体）支持F1（这些候选为空实现）；E2（ImageSizeInfo与builder字节）支持F2（SA参数和地址传递明确）；E3（SA原包窗口）支持F3（程序身份明确、ISA语义未知）。实际路径止于SA程序执行边界，不跨越为原JPEG像素布局或已消费帧的证明。

剩余精确问题是selector=0的RC固定模式中，`A+0/+1/+2/+3`分别对应哪些Y/Cb/Cr样本，以及该定义如何与JPEG memory-source保持一致。尚无可命名的ASIC byte-order字段回答这个问题。`native_pixel_layout_known=false`、`guest_pixel_consumed=false`、`capture_verified=false`保持。
