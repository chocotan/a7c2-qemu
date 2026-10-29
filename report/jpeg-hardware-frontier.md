# 原JPEG硬件接入：已知寄存器与剩余边界

原 `Without_Pin` 路线已确认是元数据/请求包装器，后端仍使用JPEG硬件；独立[内存JPEG引擎](virtual-jpeg-engine/README.md)已经能够实际压缩调用者像素并独立解码，但还没有接入原guest数据通路。以下是下一步接线的源码调查边界，不是硬件运行收据。

仅使用公开 `runtime/analysis/menu-root/system/av-cam.bin`，13,797,088 B，SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`。下列K均为raw文件偏移，不能与CP的raw+108000规则混用。B为原驱动寄存器KVA，P为驱动参数，L为设备配置对象，S=L+90，O=L+70；偏移为十六进制。

## 已识别的数据流

| 路径 | 源地址/寄存器 | 已知内容与限制 |
|---|---|---|
| 设备地址 | K2a3e34查K3eebc0，K2a3e24 OR `ffffffff00000000` | low words为f3020000/f3030000/f3040000/f3120000/f3130000；后续已用官方DTB与原map_io独立核实它们对应同值AP物理地址，见下节 |
| 输入地址 | B+1218、B+800 | K2aa3e8计算源地址，K2aeed4转AIF，K2af780/2af9a8将参数送2a510c/2a4650；高位编码不是普通high32 |
| 输入遍历 | B+80/+84、B+804..824 | 已调查内存分支为2×CanvasX字节行步进，target宽/高按16/8取整、访问宽按128取整，使用256 B访问块；分量顺序未证明 |
| 输出范围 | B+1298、B+12a0/+12a4 | K2aa760(P+30,O,3)，K2af698→2a476c；输出写点还带原JPEG头预留区和对齐，不能当裸buffer起点 |
| 输出长度 | B+44、B+4c | K2a49c4等待 `read32(B+44)&3f`，读长度，再向B+40写1；最终长度还加23d |
| 启动/状态 | B+8、B+10/+14 | K2af620→2a3e48置启动bit0；K2aef98→2afcf8读状态并回写，随后原事件派发；完整状态/错误/清理仍需实现 |

对P+50=0内存分支，输入地址算术为：

```text
C = u32[P+08]
A = u64[P+00] + 2*((u32[P+14]+u32[P+24])*C + u32[P+10]+u32[P+20])
```

K2aeed4的表K3320d8将A转换为AIF；原范围 `[0,100000000)`、`[100000000,200000000)` 加400000000，`[3fe000000,3fe6c0000)` 减300000000。随后保存 `(AIF>>24)&ffffff00` 与low32。以上仅记录所追分支的具体源运算，不把它推广为任意guest地址转换或输入像素格式证明。

输出参数的源运算为：

```text
a = u64[P+30]; cap = u32[P+3c]; off = u32[P+40]
E = a + off + 23d
D = E & ~f
O+0/+4 = phys2aif(D)
O+8 = D
O+10 = u16(E-D)
O+14 = u32(a-D+off+cap) & fffffff0
```

另一个B+90值来自cap-63d或0的无符号条件选择，不与B+12a4混成同一容量字段。

## 输入路由字段不是像素分量顺序

后续4个原窗口共1152 B已独立核，见 [jpeg-pixel-routing-source-pins.json](jpeg-pixel-routing-source-pins.json)。K62984..629a8两次调用K61ee8给P+50/+54和P+58/+5c赋值；对应DataSite映射0..5→0,0,1,2,2,3与IibNumber映射0/1→0、2..8→1..7。

K2acc40..2acc4c调用2aaaf0构造L+68路由块，再由K2a52fc写B+1200的bit11、bit12、bits19:16。内存P+50=0分支只明确写L+68=0，未在该分支写L+69/L+6a；上游K2aab4c初始化仍须单独核，不能将其它路由位当已知0。这些位没有已证YUYV/UYVY/VYUY或plane-layout意义。

L由K2aab34解析为KVA(K46eac0)+sign_extend_8(device)×1d8，这是静态存储地址，不是已证live buffer/lease或BSS界限。源端仍需闭合parameter1054像素SDS的真实写入布局或ASIC内存源解释。DataContent2、2×CanvasX步进和单个计算源地址，都不单独证明分量顺序、单plane或plane偏移。

## 官方DTB与实际mapper闭合物理地址

公开 `runtime/analysis/unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb` 的完整SHA-256为 `c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280`。主会话独立读取FDT结构，节点 `/iomem@0xf0000000` 的实际属性为 `device_type=iomap`、phys=f0000000、virt=fffffffff0000000、size=0e000000、memtype=1。

原GPL内核 `arch/arm64/mm/mmu.c` 的 `map_io()` 读取这些属性，并以phys/virt/size/prot调用 `__create_pgd_mapping`。因此device0的KVA fffffffff3020000对应AP PA f3020000；其余四项相同推导为f3030000/f3040000/f3120000/f3130000。这是DT和实际mapper共同证明，不能省略为任意截断KVA的一般规则。实际设备窗口大小和完整IRQ接线仍未证明。

另需撤回表45..49作为IRQ候选的过宽描述：原 `K2a5708→2a067c` 是同步选择器配置，原标签K450354为 `ddls_jpeg_set_syncsel`。值45经跳表选择offset21e0，最后写KVA fffffffff34021e0=8；它没有注册Linux IRQ，不能由此计算GIC SPI=45−32。主会话已独立核基址表和该label。

后续[IRQ路由调查](jpeg-irq-routing/README.md)已补上真正注册：五路LIRO/Linux IRQ61..65，由原GICv2/UDIF固定32..87映射到同值GIC INTID；QEMU外部输入为29..33。device0的handler为av-cam K2aef90，LIRO原应答写GICC EOIR PAf13a2010。编号/物理接线合同已闭合，实际guest注册/使能/target/触发/状态清理与压缩完成仍待验。

## 为什么完整JPEG不能直接复制给原驱动

K2acdbc..2ace54会检查硬件输出E处为 `FF DA`（SOS）。后续K2ac7a0在前面写原JPEG表头，最终报告长度=`read32(B+4c)+23d`。因此当前内存引擎输出的完整JPEG还须适配为与原量化/Huffman配置一致的SOS后段。只丢掉文件头、只交裸entropy bytes，或忽略原表配置，都不足以保证原固件组合出的JPEG正确。

## 下一组必须闭合的接口

1. 设备窗口大小和原驱动所需的完整MMIO行为；KVA→物理地址已由官方DTB/map_io闭合，device0为f3020000。
2. 输入2 B像素的分量顺序/组织；不能将其命名为RGB888、YUYV或UYVY。
3. 原配置量化/Huffman表到内存引擎的绑定，以及正确的SOS后段输出。
4. 长度FIFO、DMA清理和IRQ完成：source合同为LIRO/Linux/GIC INTID61..65、QEMU外部29..33，EOIR为f13a2010；还须实际消费注册/使能/target/状态/应答。45..49实际是syncsel配置值，不当作GIC IRQ。
5. guest实际请求、输入lease、输出回收，以及原Fsys保存后的独立解码。

Evidence E-JPEG-source来自公开原件的有界反汇编/表读取，Finding F-SOS是原驱动要求硬件SOS输出而非完整文件。Path P-hardware（dataflow）为原80 B请求 → 驱动P → AIF/DMA参数 → MMIO压缩 → SOS输出/长度FIFO/IRQ → 原头部组合 → 原Fsys。该路径目前止于接口合同，尚未执行；`capture_verified=false`、`guest_pixel_consumed=false`、`JPEG_hardware_verified=false`。
