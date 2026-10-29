# AP端的CP数据记录：已证取址，未证启动上传

本项补充原`backup.ko`到公开Backup文件的取址边，仍不能把第二记录当成当前CP primary。

主会话只读原模块、公开ALLLANG seed及ELF重定位；未运行内核模块、访问设备、调用DMA或修改固件。`verify_ap_cp_backup.py`已实际通过，它只检查原件身份、指令、重定位目标和公开文件布局。

## 已证的一条新边

原模块SHA `167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b`；地址均为ET_REL的`.text+offset`，不套appFw VA或CPVA。

`Data_getAdrs`（`.text+5988`）在type=1时，读取根header的u32 `+18/+1c`，计算`align_up(header_size+payload_size, 0x1000)`，加回根地址，再检查格式版本。公开seed的结果正是`ed000`。该记录实际长1419512B，首word为04000000，BK4标记有效。这证明AP的type1选择规则，超出“扫描找到了第二个magic”的弱证据。

`backupfile_get_cp_data`（7030）实际执行：

1. `Data_GetHeader → Data_getAdrs(header,1)`，得到这段记录；再用`Data_getSize(header,1)`取得尺寸。
2. 7074读取该记录首u32，交`arch_p32_to_p64`，存DMA描述结构`+8`。
3. 同一记录指针交`arch_va_to_phys`，存描述结构`+10`；回调经重定位为`backupfile_cb_getcp`，回调只发完成信号量。
4. 70bc调用`pcidma_transfer_async`，成功后等待完成。仅调用/排队返回0不足以证明搬运已完成。

另两条显式DMA路径是`backup_get_cp_rd_data`（71c0）和`backup_put_cp_wt_data`（72b8）：它们在描述结构`+8/+10`以相反顺序放入固定地址`0x404300000`与调用方缓冲的物理地址；前者控制字节+2为0，后者为1。它们是区分读写方向的后续线索，不能只凭函数名定义PCI地址域。

## 仍缺的边与明确边界

本模块三处直接重定位到`pcidma_transfer_async`的调用已穷举为70bc、7220、7318；这不是对所有间接调用、其他模块或bootloader的排除证明。

当前尚未把AP文件记录的字节、PCI源/目标地址域和CP启动前的04000000内存写入连成一条链。`backupfile_init`（6540）先读文件header，通过首word推导既有映射；仅在指定模式下重读文件到该映射，再`Data_init`。不能反过来把运行期“取得CP数据”路径当成启动期“给CP送配置”路径。

因此SOURCE.md与SHADOWS.md的拒绝点继续有效：未证明原始装载/选择前，不提升第二记录、不合并两bank、不向CP shadow写资源来跳过3006。下一步要核**启动加载器或PCI DMA提供者如何使用type1记录，以及它相对55dcc6的执行顺序**。当前仅缩小来源问题，未恢复CMOS、镜头或3006。

复核（从本成果根目录）：

```bash
python3 -B report/cp3006-start/verify_ap_cp_backup.py
```
