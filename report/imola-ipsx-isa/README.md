# Imola控制字：MIPS32/64工具选择与条件反例

MIPS32默认解码失败不足以证明厂商自定义指令；同一字在标准MIPS64中可解码为LDL/SDL。另一方面，已核的一条前驱路径中，标准LDL无法从内存改变轮询所需bit0。**实际GPR位宽和这些字的运行语义仍未知**，没有选择原生MCU CPU或将指令改成NOP。

范围为公开Imola2固件的只读静态核查，无MCU/系统VM、网络或物理设备。完整身份与8窗口4256B见[source-pins.json](source-pins.json)；[test_isa.py](test_isa.py)两项检查已通过，仅验证原字节与标准ISA假设下的不变量，不执行厂商操作码。

## 两种解码

完整函数80748298..80748334（含return delay slot）156B，SHA cc093e4089dddeb4e94eb9c8a9fa761a5bb6cc31bb4b2b0ab3bc115972a22289。

| VA | 实际文件字节 | LE word | 标准MIPS64 LE |
|---|---|---|---|
| 807482c0 | 00 04 e5 68 | 68e50400 | ldl a1,400(a3) |
| 807482f8 | 00 0d e2 b0 | b0e20d00 | sdl v0,d00(a3) |
| 80748304 | 01 0d e2 b0 | b0e20d01 | sdl v0,d01(a3) |
| 80748310 | 03 0d e2 b0 | b0e20d03 | sdl v0,d03(a3) |
| 8074831c | 04 0d e2 b0 | b0e20d04 | sdl v0,d04(a3) |

807482a0是`s1=a0+9c0`，不是把该指针写入a3。后续s0=s1+1c8；四个leaf getter返回u32[s0]的6..9、10..13、14..17位及u32[s1+8]的bit22，各自喂给上表store，均不改a3。完整函数没有LDR/SDR配对。该观察不单独证明厂商语义。

## Canonical基址复现

MIPS64的LUI会符号扩展。零扩展80000000的静态坐标不能用于否定高地址global映射。主会话补完代理未取得的canonical Kuna结果：

```sh
mkdir -p runtime/analysis/scratch/imola-static
python3 report/imola-mcu-firmware-contract/image.py \
  runtime/analysis/menu-root/usr/codec/vcd_firmware_imola2.bin \
  ram1 runtime/analysis/scratch/imola-static/ram1.bin
kuna decompile-all runtime/analysis/scratch/imola-static/ram1.bin \
  --raw-image --target MIPS:LE:64:default --base 0xffffffff80714000 \
  --addr 0xffffffff80748298 --option rawdiscover off \
  --max-fn-seconds 8 --max-fn-memory 256 --no-vars
```

实际命令RC=0，恢复完整函数。导出RAM1为1748992B、SHA015030f15297ff345fcf9faa5246d0dc31a97664b6da504974293fd2a31edbf4；本地复现收据在`runtime/analysis/scratch/imola-static/canonical64-reproduction.json`。工具将这些字解释成标准LDL/SDL的合并表达式；这只证明工具接受该目标。

## 条件LDL不变量

前驱80748334在80747e6c/74先后被调用。已追踪的成功负指针分支给出a3=ffffffff80747e34、a1=ffffffff807ae960；三个bit字段不是4的子分支进入相同字68e50400轮询。头两个getter不改这两个寄存器。

若采用标准小端LDL，则EA=a3+400=ffffffff80748234，EA&7=4，左移24位，同时保留old_a1低24位：

```text
new_a1 = (memory64 << 24) | (old_a1 & 00ffffff)  [结果取64位]
```

因此`andi a0,a1,1`始终得到原来的0，改变memory无法使这个分支观察到ready。测试检查全部64个单bit内存值、全0/全1以及old bit0=0/1，不变量成立。canonical符号扩展不改变EA低三位，反例仍成立。

该结论仅挑战**这条条件路径的标准memory-ready-poll解释**。没有观察其在当前capture实际执行，也未闭合字段4分支的额外helper（8077fd00..30）。不能把这个反例推广成整份固件不可能是MIPS64，或据此发明位域store语义。

## Status与尚缺证据

ROM1曾写Status10400000，KX/SX/UX为0；这不证明GPR32。现有QEMU MIPS `target/mips/internal.h::compute_hflags`对ISA_MIPS3 kernel模式独立许可64位指令；KX等另控制扩展寻址。LDL公式可对照`target/mips/tcg/translate.c::gen_lxl`。本次未读出可证明AT/AR的实际Config值，CP0寄存器25仍不命名为已证标准EBase。

E1（原字和多目标解码）→F1（32默认拒绝不是自定义ISA证明）；E2（完整调用与保留低位）→F2（条件标准语义不满足memory poll）；E3（canonical成功）→F3（消除错误静态坐标造成的假否定）。下一步需正向CPU位宽/厂商语义及字段4 live-in证据。MBP普通LW/SW的端口协议独立成立，仍不足以执行实际编码。`MCU_executed=false`、`capture_verified=false`。
