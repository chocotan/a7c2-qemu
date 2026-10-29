# 原DMA330与PL330虚拟硬件：有限验收

这里是本项后续维护的权威源码目录。原`scratch/sony-pl330*`及`dma330-probe`保留历史实验、失败和私有运行输出，不再维护另一份交付源码。

已验证：原4.9.337 kernel加载自有映射适配模块及原DMA330，通过原异步API提交1项256B请求，原编译器生成微码、PL330实际搬运、原IRQ和callback完成。main独立核3个完整QMP页、源/目的整页哨兵、descriptor、callback/status/cookie/submit、正常IRQ1/abort0、无迟发fault、CPU恢复及正常退出。详见[验收与失败定位](../imaging-pixel-contract/DMA330-RUNTIME.md)和[请求/完成合同](../imaging-pixel-contract/DMA330-REQUEST-COMPLETION.md)。

范围是**controller0/channel0的一项原驱动请求**；硬件qtest另覆盖16个non-secure通道、3类冷启动故障、预取残留与跨tag所有权、原始程序重放。不是相机固件图像消费、LIRO装载、CMOS/AF、照片或录像验收。没有把原SD、GUI默认入口或稳定二进制改成实验配置。

## 组件与修复

- `qemu-dma330.patch`：固定QEMU11.1.2、已有native/USB补丁之上的增量。opt-in双PL330、原资源与p32地址空间、8个non-secure事件，真实MemTx错误处理，DMAEND等待实际队列后仅flush本tag，以及正确的tagged FIFO压缩。默认设备关闭。
- `sony-pl330/`：可重建候选的源码变换及硬件测试。候选只生成在独立目录，不自动安装。
- `sony-pl330-mmio/`：原UDIF映射API创建两项4KB映射，PID核验后仅发布16个virtual资源字段；失败不发布并回滚。无unload，生命周期为该VM。
- `sony-pl330-client/`：正常kernel页分配、实际物理域检查、cache维护，原API单请求；buffer/request由resident模块保留到VM退出。
- `dma330-kernel-client-abi/`：独立生成的模块描述、marker-only基线和严格ELF/破坏测试；不复制Sony模块blob、不强制跳过loader检查。
- `dma330-probe/`：隔离原kernel受控试验。只用专属Unix QMP；没有callback时保留VM/管道/锁，不回收未知owner。
- `admission.py`：共享锁及pidfd等待；不杀外部VM。`verifiers/`包含原字节和整体验收工具。

## 在本成果的已导入原生环境中复现

依赖原生runtime已准备的只读ALLLANG资产、原kernel、原模块/库及`menu-initramfs.cpio`。原资产和QEMU归档由使用者准备；本目录只交付源码、补丁和文档。必须先结束项目其它相机VM，不能绕过共享admission。

在本目录运行：

```bash
python3 -B prepare_modules.py
python3 -B sony-pl330/build_candidate.py
# 取构建输出的PL330_CANDIDATE_STAGE，以下使用其绝对路径：
python3 -B sony-pl330/test_hardware.py "$candidate/build/qemu-system-aarch64"
python3 -B dma330-probe/run_probe.py --resources --snapshot-registers \
  --mmio-adapter --dma-client --pl330-candidate "$candidate"
# 取探针输出的DMA330_MODULE_PROBE_RUN：
python3 -B verifiers/verify_original_dma.py "$run"
```

`candidate`和`run`是用户根据实际输出设置的本地路径，不预设最近一次运行。qtest可另传`--original-fixture "$prior_run"`重放本地原微码；含原微码的fixture不随源码包分发。

构建无网络并校验归档/native/USB身份及最终两个QEMU源文件摘要，`SOURCE-ORIGINS.json`记录来源。参考4.9.186头文件不用于伪装4.9.337 ABI。所有host mock只核控制/rollback；实际完成必须再过guest和独立QMP数据检查。

## 当前限制

完整reset、运行中卸载、其它原驱动通道/大尺寸/多描述符/异常恢复尚未验收。源码中的无unload是资源所有权约束，不能在driver使用期间强制卸载。进入pending保留实例时，先调查/恢复原请求再决定结束，不能强杀后报告成功。

DMAEND修复根据[ARM DDI0424A §4.3.2](https://documentation-service.arm.com/static/5e8e23bffd977155116a5342)：传输完成后进入Stopped，并清除本线程MFIFO。仍等待原read/write队列，不丢弃待写出的数据。官方手册原件和Sony原资产不纳入本源码目录。
