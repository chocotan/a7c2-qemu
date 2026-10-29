# 原厂ATU请求诊断客户端

主会话已核对并在本目录独立重建代理交付源码：38个ASan/UBSan主机控制测试、10个ELF检查测试通过。模块为6784B，SHA `7a901c75d6aaf048065de652588eb45d11fb66b1e5569a8869dae085f341b34a`。host别名测试只检查诊断分支和资源控制，不能证明ATU硬件工作；guest内容判据单独由`../observe_client.py`处理。

正常模块导入仅为`pciatu_map`、`pciatu_unmap`、`udif_ioremap`、`udif_iounmap`和`printk`，依赖原`pcieatu`；保留原vermagic，重定位仅ABS64/CALL26，无exit回调。ABI检查器通过相邻的`virtual-dma330`组件加载，代码不再依赖外层研究工作区路径。

客户端在原固定I/O mapper和原`pcieatu.ko`之后加载。它请求1MiB PCI目标04000000，使用原API返回的本地C窗口，普通ioremap只映射首个4KiB；另映射显式TESTPCI peer的观察alias600000000。该地址对应虚拟16MiB测试RAM，不是CP的同数值地址或CMOS缓冲。

实际数据顺序是：从观察alias初始化4KiB guards和256B payload，经aperture读取核对，从aperture写不同的256B数据，再从观察alias核对实际结果及全页guards。没有用从源到目的的CPU复制替代映射访问。之后必须原`pciatu_unmap`返回0，且本槽control bit31清零。CPU不再访问失效的aperture。

成功建立的IOMEM和模块保持resident到VM退出；只有尚未访问数据的失败setup执行原iounmap回滚。不明槽号、unmap失败或enable不清都会报告`OWNER_UNCERTAIN`，运行器保留VM、控制通道及admission。`insmod`返回0本身不代表数据通过。

构建（先确认没有本项目VM正在读取源码／模块）：

```bash
bash build.sh
python3 -B check_client.py
```

从上级`virtual-atu/`启动隔离guest验收：

```bash
python3 -B ../virtual-dma330/dma330-probe/run_probe.py \
  --atu-provider --atu-client --pl330-candidate "$atu_candidate"
```

运行器核原模块身份、Uid/Gid、普通模块加载和真实export，再核本客户端身份、实际数据／guards、同槽释放及禁用。成功后另以QMP保存实际peer全4KiB，独立计算模式和guard摘要，并读取物理control确认禁用，恢复CPU后取得新guest输出。只有这些证据与正常退出齐备才接受。

guest `trial-0f21_yef`已实际通过，主会话独立核对原始输出、物理control和实际peer全页；详见上级`original-api-validation.json`。原map返回slot0/C0000000，原unmap返回0，control=0，peer全页SHA `1ecc5711bb77b2d4500e9b800087eb3a59332b147d602bc58e7d30293ab875ac`，CPU恢复与正常退出通过。只验收原API的一次1MiB映射及256B payload／全页guards，不泛化全部slot、并发、reset或多窗口重叠的原驱动行为。

原provider装载证据另有`trial-fxzqq_18`；其原SHA、RC0、Live和两个真实导出通过，正常退出。provider装载、此测试的CPU aperture访问都不代替PCI DMA、ICDT、LIRO帧消费或拍摄验收。静态ABI检查器只报告其自己的检查范围，不自行推断模块是否曾在guest装载。
