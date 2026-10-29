# 原ICDT：DMM句柄到PCI DMA及正常退休

这是静态合同，不是ICDT已运行或图像已传输的证据。主会话收取调查后，用原指令纠正wrapper核验的地址笔误（f24是ldr x1，f28才是callback/cookie pair，f2c读取src，f30调用inner），再实际运行`verify.py --capture`。77条指令锚点、原件SHA、模块两目录扫描、重定位、方向门槛和kernel导出均通过，写出`raw.json`；原失败日志保留。

原`icdt.ko`为21776B，SHA `8784a3ec17fac03339f912fa1eb8f3d969970220dcb9c8ea05b3b96a3e9aab22`。原kernel为6610952B/SHA `620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2`，这里是原Image，非4.9.186参考树。

## 请求不是任意散列表

|request偏移|类型／含义|
|---|---|
|+00|src endpoint指针|
|+08|dst endpoint指针|
|+10|u32 byte_count|
|+14|u32 type|
|+18|callback|
|+20|cookie|

endpoint为`u32 DMM_handle, u32 byte_offset`。模块.text+2c8按handle bit15选择原DMM队列8061003c或9061003c，发送40B消息op2a，handle位于+8。回复op802a，signed status+2、segment count+8、16B address/length记录从+18h开始。不能提供伪DMM回复、把句柄当CPU指针，或把任意用户散列表直接塞入请求。

现有有限DMM测试服务只支持op20..23及其自有两slot backing；尚未提供2a。实现查询前必须绑定真实allocated handle、generation、对应实际backing及正确地址域，不能直接宣布所有handles可用。

## 低层描述与原provider

ICDT.text+5d0产生24B entries：`u32 control, u32 length_bytes, u64 src, u64 dst`。数据control1、最后数据control9，终止link为control6/length0并存放物理list地址。地址是否处于本地／PCI域由两端原门槛及DMM回答决定；旧报告只支持单向的推断已更正，不能以它限制原两向路径。

两模块目录共4个kmod及120个usr/kmod被扫描。真正`pcidma_transfer_async`是原kernel导出，Image+2a20c8，链接VA ffffff80083220c8；不是缺少一个未找到的ko。返回0只计接受／排队。

## 回调与退休

正常kernel IRQ调用`callback(status0,task)`，进入ICDT.text+d0，再调用用户`callback(status,cookie)`。之后.text+70把退休消息送至02820772；worker.text+138按实际分配器用kfree或__udif_kfree释放task，再free OSAL消息。abort为status-1，ICDT原样转发。

因此callback早于task退休。退休发送失败可能保留owner，不能看到callback就释放上游全部资源。下一项已定位到原kernel Image+2a1e80硬件编程边；MMIO、PCI地址域、真正完成及原DMM消息交付仍需单独运行验收。

## op2a/802a 布局已钉住并在测试DMM服务实现（本轮新增）

主会话从原`icdt.ko`（21776B，SHA `8784a3ec…`）`.text+2c8`函数反汇编核定，真实指令消费证据：

- **op2a请求**（40B）：`+0`=op `0x2a`（strh），`+8`=u32 handle（str w22），其余全零（stp xzr/stp xzr/str xzr）。队列按handle bit15选`8061003c`/`9061003c`（csel，ubfx x23,w22,#0xf,#1）。**op2a即"按句柄查询物理段"**——ICDT用回复的段建LLI描述符。
- **802a回复**：`+0`=op `0x802a`（ldrh比对），`+2`=s16 status（ldrsh，须0），`+8`=u16段数（ldrh），`+0x18`起16B记录：消费端`ldr x1,[record+0]`（u64地址）与`ldr w1,[record+8]`（u32长度）。

`runtime/analysis/dmm-service.c`据此实现op2a：与op21..23同一handle/generation/allocated绑定校验，成功时回1段（地址=该slot的CP侧物理，沿用op20/21回复已证约定`physical-0x400000000+index*0x80000`，长度0x80000）。自测（ASan/UBSan）新增op2a用例：活句柄回正确段、stale generation→-5、index越界→-5、不扰动slot状态，全部PASS。**单元级证据，不是ICDT运行或图像传输证据。**

运行时op2a需guest的icdt.ko在真实成像传输建立时发出，依赖LIRO/帧管线——那仍是Task74后续前沿。地址域从CP侧到AP侧的映射（arch_p32_to_p64）在下游，op2a本身按既有CP约定回答。

## udif_interchip_datatrans入口核验（本轮新增，静态）

`icdt.ko`仅export`udif_interchip_datatrans`（symtab st_shndx=14=.text，st_value=0x28，size 0x80，info 0x17）。真实入口从`.text+0x00`起：`ldr w3,[x0]`取request+0段数→cbz→循环`ldr w4,[x2],#0x10`对request+0x10起每条16B记录的+0字段求和→`ldr w2,[x0,#4]`→`sub w3,w3,w2; cmp w3,w1; b.lo`与参数byte_count比对，和小于则返回1（错误），否则0。**该export是段长度校验包装器**，真正传输提交（→DMM op2a→LLI→PCI DMA）在更深处，尚未钉住。runtime op2a需guest装载icdt.ko并由成像链发出真实传输请求，依赖LIRO/帧管线，仍是Task74后续前沿。

## ICDT传输提交编排已钉住（本轮新增，静态）

`icdt.ko`的CALL26/JUMP26重定位与内部`bl`目标核定完整路径：

1. 公共入口`udif_interchip_datatrans`（唯一export，symtab value +0x28）。
2. **提交函数`.text+0xa50`**（被`+0xf30`/`+0xfa4`调用）编排：
   - `+0xb80` `bl +0x2c8` — op2a查询**src端点**（句柄→物理段）；
   - `+0xbd0` `bl +0x2c8` — op2a查询**dst端点**；
   - `+0xc0c`/`+0xc20` `bl +0x00` — 对两端段表跑校验包装器；
   - `+0xd0c` `bl +0x5d0` — LLI构建器（24B entries，control1数据/control9末数据/control6终止link）；
   - `+0xd20` arch_va_to_phys取LLI物理地址；
   - `+0xd48` osal_valloc_msg_wait分配task消息；
   - `+0xd90` **pcidma_transfer_async**（原kernel导出）真正提交。

即：**每次interchip传输对src/dst各发一次op2a**，DMM服务两端各答一次802a（物理段），ICDT据此建LLI后交PCI DMA。这印证op2a实现方向正确。

**装载现状**：icdt.ko**不在**initrc默认装载（只有n.ko），且全kmod目录扫描仅icdt.ko自身引用`udif_interchip_datatrans`——无其他kmod经ksymtab导入，消费端走用户态接口（proc/sysfs/ioctl）而非内核符号链接。runtime op2a需要：装载icdt.ko + 由成像链（LIRO等）经该用户态接口发出真实传输请求 + DMM分配真实句柄。这依赖LIRO/帧管线，仍是Task74后续前沿；本单元级op2a实现与提交路径钉住不冒充成像传输已运行。

## 运行时装载证据（本轮新增，真实guest）

`run-w5qa8lck`（MENU_EXTRA_MODULES=safe，含op2a分发器的观察者重建）：icdt.ko在真实guest**装载成功**——`MOD_OK icdt`，内核日志`initcall init_module+0x0/0xf28 [icdt] returned 0 after 287 usecs`，无未解析符号/无init fault。其用户态客户端`libInfraInterchipDatatrans.so`（282_）真实加载并就绪：`RCV_SITE tid=226 queue=0x282078f timeout=4294967295 caller=/usr/lib/libInfraInterchipDatatrans.so+0x96c`（在其接收队列上等待）。

**诚实边界**：本次运行未触发成像操作，故**无真实transfer请求发到queue 0x2820746，无op2a发到DMM queue**（console无op2a的DMM_REQUEST）。op2a在runtime真正触发需要成像管线（LIRO等）经libInfraInterchipDatatrans发出真实interchip传输请求——那依赖LIRO/帧管线，仍是Task74后续前沿。本证据只证明icdt.ko可装载+客户端就绪+op2a路径已接线（分发器+服务模型），不冒充op2a已在runtime执行。

## 用户态触发API已钉住（本轮新增，端到端链闭合）

`libInfraInterchipDatatrans.so`（5960B）export `interchip_transfer_async`（+0x990）与`interchip_transfer_user_init`（+0xa1c）。`interchip_transfer_async`（真实指令证据）：osal分配0x30消息→把调用方40B请求**原样拷贝**（ldp/stp +0/+0x10/+0x20三段）→发到queue **0x2820746**（同步，bl osal_snd_sync_msg）→取回`[msg+0x28]`status→释放。请求布局与icdt.ko回调读取完全一致：+0/+8=src/dst endpoint指针、+0x10=len、+0x14=type、+0x18=callback、+0x20=cookie。

**端到端op2a链路全钉死**（每环均有真实指令/运行时证据）：
LIRO → `interchip_transfer_async`（libInfraInterchipDatatrans.so +0x990）→ queue 0x2820746 → icdt.ko sync回调（.text+0xf40）→ 提交（+0xa50）→ 每端点 op2a（+0x2c8）→ DMM queue 0x9061003c → **本服务模型op2a（已实现+分发器接线+单元测试）** → 802a物理段 → LLI构建（+0x5d0）→ arch_va_to_phys → `pcidma_transfer_async` → PCI DMA搬运（Task77已验）。

op2a在runtime真正触发仍差最后一步：成像管线（LIRO）须以真实DMM句柄调用`interchip_transfer_async`。那依赖LIRO/帧管线装载与帧请求，是Task74最终前沿。

## liro.ko装载性核查（本轮新增，静态）

`liro.ko`（121488B）136个import**全部可覆盖**：backup.ko提供35（Backup_*系列）、osal_uipc.ko 22、osal_utm.ko 7、pcieatu.ko 2（pciatu_map/unmap）、dmm.ko 1（dmm_direct_call）、icdt.ko 1（interchip_transfer_async kernel侧）、dma330.ko 1（dma330_mem_transfer_async），其余69个为kernel导出（含hwtimer_*/pm_*/subsys_*irq/tmonitor_*/udif_driver_*/udif_perr_enable，已逐一grep原vmlinux.bin确认PRESENT）。

即liro.ko可装载，前提是backup+osal_uipc+osal_utm+pcieatu+dmm+icdt+dma330全部先装载。这印证op2a链路的上游触发方（liro经interchip_transfer_async）在依赖满足时可装载。**可装载≠已发首帧**——LIRO发真实transfer仍需其成像会话建立，依赖帧管线装载与场景/传感器输入，是最终前沿。

## liro.ko装载机制（本轮新增，静态）

liro.ko**不由initrc装载**（insmod_drv1/drv2均无liro行；icdt.ko在drv2，紧随dmm.ko）。liro被`appFw.so`/`libIMDB.so`/`av-cam.bin`（文本引用确认）在成像启动时**动态insmod**，参数`fn=`（CP固件文件名string）、`adr=`（装载地址ulong）、`load:int`、`delay:int`、`debug:int`、`resume_cpu:int`、`liro_resume_async:int`。depends=backup,dma330。

即**LIRO是CP固件装载器/成像会话桥**：成像启动时动态装载，把CP二进制（cpapp-b.bin等）经DMM/PCI DMA（op2a查段→LLI→pcidma_transfer_async）搬进共享内存并建立成像会话，随后经interchip_transfer_async发真实帧传输。这是op2a的真实业务场景。

**op2a runtime触发的完整前置**：①liro.ko由appFw/libIMDB动态装载（需CP固件参数与依赖模块齐备）②CP固件装载并在虚拟CP上运行③LIRO建成像会话并发interchip_transfer。这进入**虚拟CP子系统bring-up**——一个独立大型前沿，超出本轮范围。本轮op2a/ICDT/DMM/LIRO装载性层已钉到"只欠CP子系统"。

## AP↔CP消息链路与远端发送器注册（main已核，本轮新增，虚拟CP关键）

main用kuna反编译`osal_uipc.ko`+原字节复核钉清CP队列消息路由——这是虚拟CP bring-up的挂载点：

- **`osal_snd_msg`远端路径**：queue ID若bit31置位且子系统位（0x70000000）非零（如0x92840747），走远端路径：`tst x19,#0x70000000;b.eq local`→`ldr x2,#lit; ldr x2,[x2,#0x458]; cbz→error; ldr x2,[x2]; cbz→error; blr x2`。发送器为NULL时打`[K]UIPC ERROR osal_snd_msg: No snd_msg registered. Skip snd to 0x%x`（menu运行实测0x747即此）。
- **远端发送器注册**：`osal_reg_public(a0)`把`dat_40cd18=a0`（已注册返回0xfffffc06）。**发送器签名=`sender(queue_id, message) → long`**（main核：远端路径不破坏原始参数，x0=qid、x1=msg原样传给blr）。
- **属主=`pcie-if.ko`**：全kmod扫描仅pcie-if.ko import `osal_reg_public`。它exports `udif_pcieif`，imports `osal_reg_public/osal_unreg_public/pcidma_transfer_async`，depends `osal_utm`。即**pcie-if.ko是AP↔CP链路驱动**：注册远端发送器，用`pcidma_transfer_async`（Task77已验）把CP队列消息经PCI DMA送到CP。

**虚拟CP bring-up路径**：①装载pcie-if.ko+pcieatu.ko+pci_ep_cp.ko（需PCIe/interchip模型支撑，Task76/77已有DW host/ATU/PCI DMA），让它注册远端发送器并建链路；②CP端（PCI endpoint）建模接收消息、产帧、经PCI DMA回传。**或**最小bring-up：自定义诊断模块调`osal_reg_public(自研sender)`接管CP队列（合法insmod，不force vermagic），把当前"No snd_msg registered"的黑洞变成可捕获的真实帧请求——这是理解帧生产协议的最小切入点。
