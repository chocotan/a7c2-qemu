# Imola结果IRQ、共享完成环与0500发送

原0500发送链已闭合到IRQ handler对硬件可见80字节（十六进制，即128B）结果环的读取与序列化。实际写入该环、P/Q结果内存和ES编码字节的MCU函数仍未闭合。不能据此生成成功状态、触发伪完成或清除录像缺口。

本次只读公开av-cam.bin、codec_drv.ko、liro.ko；无系统VM、网络、硬件或物理SD，不读取private/full。K为av-cam raw，原KVA=ffffffc001000000+K。完整资产身份与12窗口8152字节在[source-pins.json](source-pins.json)。

## 原中断到实际队列

Kbd70d8是四个u64 `{29,0,ffffffc0012293bc,1}`，位于已验证2f934注册循环的同一T_CINH表。因此实际IRQ编号29十六进制=41；沿既有[LIRO/GIC合同](../jpeg-irq-routing/README.md)，GIC INTID41、QEMU外部输入9。未在guest触发验证。

2293bc读取全局状态S、暂时修改mask，依次检查3ec2d0中的9个掩码100..10000。channel selector表44d20e为0..7及ff；ff有独立路径，不是普通channel8。对通道状态V，它结合低8位和保存的wrap generation排空结果，调用267c70读取当前slot，复制到E+10，调用2295f0发送，再268c30回写消费游标并恢复本次mask位。

E是先清零的90字节对象，明确写E+2 u16=0500、E+4 u16=90、E+8=V>>31、E+9=(V>>29)&1、E+a=(V>>30)&1、E+b=实际channel，再copy完整80字节D到E+10。原代码调用结果getter后没有检查返回值便发送，所以消息出现不证明getter或编码成功。高三位也不能统一当作成功标志。

2295f0以常量806800f3分配、复制并发送90字节；2135e0把同一常量传给295c64并保存到接收对象G+8。因此这条IRQ/共享环读取真实连接到既有2961bc的0500接收器，不再只是两个相似消息格式。

## MMIO和完成环

以下是原指令访问的KVA；低32位PA的使用承接既有Sony IO alias合同，不能将新寄存器泛化为W1C。

| KVA | 原行为 |
|---|---|
| fffffffff3800090 | u32设备地址A；270914也写配置值 |
| fffffffff3804200 | 全局状态S读取 |
| fffffffff3804204 | mask RMW `(old&~mask)|(value&mask)`，随后DSB SY |
| fffffffff3804060+4*c | channel0..7的状态V；只有Kbfe304非零时271648写零 |
| fffffffff3804020+4*c | 2716f8写index OR 80000000，原消费游标 |

设备地址变换T由3323d8的原表定义：

```text
[0,100000000)                -> PA=400000000+x
[100000000,200000000)        -> PA=500000000+(x-100000000)
[3fe000000,3fe6c0000)        -> PA=fe000000+(x-3fe000000)
```

PA经332258范围检查，再调用2f500的arch_phys_to_noncache。该函数名有liro relocation/API偏移证据：模块API+620对应.rela.init.data+5d8加copy基点48。

```text
A = read32(f3800090)
H = noncache(T(W32(A+100)))
R_c = noncache(T(LE32(H+20+c*8)))
slot = R_c+(index&ff)*80
```

初始化2717b4写H+18通道数1..8、H+19=80、H+1a u16=N和各H+20+8*c设备地址。原校验N为10..100（16..256）；生成的通道地址为W32 `A+200+c*(N+1)*80`。同N保存到Kba3a34用于getter检查index<N。相邻80字节区域未恢复具名用途。有效配置值不证明slot已有有效内容。

## selector2结果及P/Q

267c70按slot[2]分派，selector2实际分支267d48。源slot+0/+1/+3与u16+4/+6直接复制；slot+8 u8→D+a，slot+a u16→D+8，slot+c u8→D+b；D+2明确置2。slot+20/+24/+28的u32复制到同offset。

关键是slot+10及+18的完整u64设备指针，分别经T及noncache转换写到D+10/P和D+18/Q。零指针保持零，转换失败走原诊断/零结果路径，不得补合法地址。这把既有[BSO_DONE/620构造](../native-video-engine-result/README.md)的P/Q接到了真实共享结果环，但仍未找到slot、P/Q和ES的writer。

## codec_drv加载服务的真实范围

codec_drv.ko是AArch64 ET_REL，已查worker/loader是OSAL文件加载服务，不是上述完成IRQ来源。worker接收818c04d5，最大118字节；command0/1分别普通/SHADOW load：request+8 u64物理目的、+10 u32容量、+14路径，arch_phys_to_noncache后bdrv_loader_file_load，经filp_open/vfs_read/filp_close读取。remaining=capacity-read_result。command4/5回复+8为加载分支结果、+c为remaining，不是编码完成。

av-cam默认路径getter21522c返回`/usr/codec/vcd_firmware_imola2.bin`（长度23十六进制）；22b600..22b6cc构造118字节请求并经2136c8发送。固件实际PC/映射属于独立MCU合同，不把MMIO+90工作区命名为MCU PC。

E1（原IRQ表/handler）→F1（读取/发送链）；E2（初始化、MMIO和寻址）→F2（完成环地址与容量）；E3（selector2转换）→F3（P/Q来源）；E4（loader服务）→F4（独立固件文件读取）。精确剩余是MCU怎样写`PA(T(LE32(H+20+8*c)))+index*80`，并在状态/IRQ前保证slot、P/Q及ES字节可见。实际CMOS/YC布局、MCU编码执行及ES生成仍缺，native gaps=63、capture=false。
