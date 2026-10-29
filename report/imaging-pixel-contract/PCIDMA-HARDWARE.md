# 原kernel PCI DMA硬件编程边

主会话实际运行`scratch/pcidma-hardware-contract/verify.py --capture`：原Image SHA、120条指令锚点、资源记录、channel布局和IRQ链通过。这里只是原字节静态合同。PCI DMA尚未运行；不能将其与已经完成单请求数据验收的DMA330合并。

原kernel SHA `620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2`，链接base ffffff8008080000，本文Image地址是文件offset。

## 原资源与启动

Image62ed00为5个资源记录，stride13b0h；DMA virtual base在record+1248h，Linux IRQ在+1238h。

|资源记录|原DMA虚拟base B|Linux IRQ|
|---|---|---|
|0|fffffffff7380000|198|
|1|fffffffff6b80000|200|
|2|fffffffff6f80000|202|
|3|fffffffff7780000|204|
|4|fffffffff6780000|206|

这是原虚拟地址，不能据此宣布物理映射或与ATU模块选项编号同一。普通固定I/O mapper方法已另证可行，具体窗口及真实端点仍要显式建立。

5cbd3c构造8个channel。`request[2]==1`的写方向first-register为`B+128h+4*n`、channel block `C=B+200h+200h*n`、doorbell `B+10h`；读方向分别`B+168h+4*n`、`C=B+300h+200h*n`、`B+30h`。

2a1e80首先写first-register=1，这不是global engine enable。2a2538另外写B+0c/+2c=1，向+58/+ac写ffffffff清pending，+90/+c4写00ff0000，+54/+a8写0以unmask。

## 真正的数据编程

非零request length：C+8长度、C+0控制8、C+0c/+10为src low/high、C+14/+18为dst low/high。零length的链表模式：C+1c/+20写64位list物理地址的低／高32位，C+0写300h。两者最后向本方向doorbell写channel编号。均为32位MMIO，未见交换byte order。

ICDT用arch_va_to_phys提供链表物理地址，链表是24B LE records `{u32 control,u32 bytes,u64 src,u64 dst}`，data1、final9、link6。原driver不在软件里逐条推进LLI。Cycle/toggle bit语义仍需硬件兼容核验，CP src/dst域尚未闭合。

## 完成与尚缺的启动条件

写status在B+4c，读status在B+a0；每channel mask为`10001h<<n`，含done和abort。硬IRQ屏蔽两bank并返回2唤醒thread。thread清channel-control bit3，向本方向+58或+ac ACK，并轮询相应status真正清除；一直不清会走fatal路径。done回调status0，abort上半位选择-1，随后清active owner、调用pcidma_run取下一项、unmask两bank。

channel+50/+58为软件计数，2a3b98是诊断ring；不能用它们伪造硬件完成。更前的`pcidma_run`需要channel+14和+18均非零。+14来自connect；+18在本轮最初未闭合，后续host worker调查已找到原producer及真实MMIO条件，主会话复验122pins通过，见[启动条件](PCIDMA-READINESS.md)。必须让原驱动从真实条件进入可运行状态，不能直接写这个字段。
