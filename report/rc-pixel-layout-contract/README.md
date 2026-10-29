# RC目标输出：provider与提交路径

本轮把此前停在`K2cff84`的resize/RC末端追到了具体provider、目标描述符构造和硬件提交helper。它仍不能确定YC各分量的字节顺序、plane数或chroma偏移，不能据此启动原JPEG或把宿主RGB当原YC。`native_pixel_layout_known=false`、`guest_pixel_consumed=false`、`capture_verified=false`保持。

范围限本项目授权的公开ALLLANG模块离线分析，不运行固件、VM或真实硬件，不访问网络、私有/full dump或物理SD。原件为`runtime/analysis/menu-root/system/av-cam.bin`，13,797,088字节，SHA-256为`90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`。以下K地址都是raw ARM64文件偏移；原KVA=raw+`ffffffc001000000`，不使用CP的`+108000`映射。

从成果根目录复核：

```sh
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib -q report/rc-pixel-layout-contract/test_source.py
```

[源合同](source-pins.json)记录本次已移交并由主线独立核对的7个主窗口，共13,868字节，另核provider对象和四个vtable槽。代理完整调查使用了更多窗口，本报告只归档已明确移交的主窗口，不把代理的12窗口总数混入此集合。工具为本机Kuna的raw-base-zero ARM64模式及Capstone；这是flat模块，无ELF导入表。测试验证原件字节与指针绑定，不执行目标代码。

| Evidence | Finding | Path |
|---|---|---|
| `K2cff84..2d0784`、`Kbfbcc8`、`K3883c8`原字节及指针 | `K2d6840`返回静态provider对象；其vtable slot18为`K2d835c`，slot20为`K2d86fc`，slot00为`K2d8c60`，slot40为`K2d7958` | 原RC末端→真实provider→构造/准备/提交 |
| `K2d835c`与`K2d7958`窗口 | builder把输入T+90的60h描述符复制到命令J+98；selector来自T+f8，额外值来自T+100 | 描述符验证→命令记录，不是像素复制 |
| `K2d86fc..2da6fc`和原调用点 | 准备器经过`K2cd23c`和`K2cdc94`形成两组目标记录，提交器把它们传给`K2d4588` | 目标记录→硬件helper；其ASIC布局解释仍缺 |

T、J、B只是本报告局部名称：T为builder的x2输入，J为命令输出，B为准备缓冲，不作为已恢复的原类型名。selector检查用`0x282`位图分出`{1,7,9}`并采用不同地址/水平对齐要求；它没有提供YUYV/UYVY等字节顺序定义。继承的1054路径实际selector也尚未闭合，不能取零或挑选某分支使测试成功。

正向提交链已具体到：

```text
K2d84cc..2d851c:
  K2d7958(T+90, u32[T+f8], u32[T+100], J+98)
  成功复制60h描述符

T+100/104/108/10c -> J+108/10c/110/114

K2d8968..2d8984:
  K2cd23c(..., J+108/+10c组成的u64, u32[J+110], u64[J+a0])
  返回值随后作为K2cdc94的x4

K2d8b40..2d8b84:
  目标记录 -> B+i*88h+20h
           -> B+i*30h+8a00h

K2d8eb4..2d8ed0:
  K2d4588(hardware_object, 两组目标记录, u32[J+108], u32[J+110])
```

下一切口已限定为`K2cdc94`目标记录构造、`K2d4588`寄存器提交，以及`K2c91f0`的实际mode来源。只有它们与实际1054参数和字节/plane解释共同闭合后，才可实现native YC消费。`2*CanvasX`、422帧头、DataContent、placement和JPEG色度矩阵都不足以单独证明packing。

本报告没有证明原驱动任务执行、输出像素已写入、generation/lease完整或原JPEG实际消费；原生CMOS→编码→MPR/Fsys→虚拟SD总验收仍未完成。
