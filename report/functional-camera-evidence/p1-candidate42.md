# P1 第四十二跑：ISCN lock mode 参数接收

本轮为原 AP 的 `0x4167 / SET_ISCN_LOCK_MODE` 请求接入既有 CP 参数 owner。原 CP handler 只把请求 byte8 零扩展后写入参数区 `+0xcfc` 的四字节，命令表 apply-control 为0，因此保留共同 apply pending，不生成独立完成回复。本轮未改 AP、EE、exclusion 或镜头状态；EE、自然快门、4038、JPEG 和写卡尚未验收，`capture_verified=false`。

范围为用户已授权的独立本机 QEMU、RAM 卡和原 App32 输入，不连接真实设备，不再委派。沿用 direct-bootin 诊断路线，不能替代 Sony loader/WBI、真实 CP 和物理看门狗。按用户要求不调查镜头伸出。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| candidate41/runtime-3 的原失败 | destination90030001、type5、4167、12B，wire `050067412b00008000000000` 返回−1020，随后原 FirmwareFault | 原 AP → 既有 CP 参数 SID → 缺失接收合同 → Imaging3109 |
| 本轮 `4167-audit.json` 的 CP 表0x10fc590、handler0x35cad0 | `ldrb [request+8]` → `str.w [0x165a720+0xcfc]`；其余条件分支仅debug日志；原表apply-control为0 | 参数字节 → 零扩展word写入 → 共同dirty义务 |
| 同审计 AP0x3537ccc–0x3537d40 | type5、opcode4167、12B、destination90030001，原发送后调用者结果置0 | 原构造 → 既有 sender → 参数 owner → 原请求free，不增加ACK |
| 两组两线程 host-validation.json、原stdout/stderr | 参数owner2项及22子测试通过，face接收/接线2项通过；新4167覆盖全部256取值、错误来源/尺寸、free失败、重入、fork、完整opcode及实际wire | 原handler独立转录合同 → sanitizer检查 → observer重建 → CPIO与生产derive |

本次 CP 输入 SHA256 为 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，AP 为 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。原二进制只读，未把其内容复制进公开报告目录。

## 修改和复现

生产修改局限于 `runtime/analysis/device-models/cp-background-device.c` 的4167、414a与400f合同，以及现有参数测试C与Python入口。原source、精确长度、owner、free、重入、继承进程和故障锁存守卫沿用不变；参数只标记实际写入的四字节为已知，邻接未知字节保留。apply completion及原CP执行仍不声明通过。

新增场景纳入已登记的 `runtime/analysis/test_cp_opcode_batch.py`，其入口已在 `tools/public-model-tests.json`；没有添加独立未登记测试。实际wire自检同时验证0和255两值、四字节零扩展、邻接未知字节和请求释放。

受管目录为 `scratch/a7c2-capture-p1-runtime-20261115-candidate42/`。先审查再运行 `prepare.py` 保存前像及原指令审计；`start.py` 依序执行 `integrate.py` 和独立运行。TMPDIR显式指向本轮目录，宿主和guest使用同一functional profile。CPIO成员集合和权限保持相同，内容变化只允许 `simulation/menu-observe.so`；新生产derive有完整摘要binding。

## 运行与收尾

首轮 `a9af` 已两组、两线程独立核收：实际4167为generation30、offset0xcfc、width4、value0、known1、request_free_rc0、handler_executed1；guest observer SHA256为 `8cfb1af49704a669da1ad728f92c89b14e251605312c9cfe7162fd0f9c7720f3`。85个归档文件与原run完整SHA相同；两笔原UPM、all13 accepted、broker attach、detach、唯一ID QMP quit、QEMU rc0、无信号及租约到退出均闭合。运行本身仍是 FirmwareFault 失败，不能用局部核收通过代替业务通过。

新首个负发送为 `414a/type5/12B`，wire `05004a412e00008001000000`，destination90030001、source80020002、rc−1020。其原CP handler0x35be5c为 `SetLiroSeqForNextBoot`，把request[8]零扩展写参数word+0x1a0，命令表apply-control为0，条件分支只debug日志。AP构造0x3538894实际发送12B到同一SID。已按原语义补入既有owner，实际wire及256值、错误来源/尺寸、free失败、重入和fork等沿用已登记测试；第二轮 `b483` 独立实验已确认414a为generation31、offset1a0、width4、value1、free0、handler_executed1。两组两线程核收通过，89份归档完整摘要一致；guest observer SHA256为 `578557f344ed846da33f0a8f5c5841430e6c8dcb9085a6c600774651f3e7dc59`，两笔UPM、all13/broker、detach、quit/rc0、无信号及租约闭合。初期ui-1导出错误原样保留，随后ui-2起恢复；未将错误帧算作画面验证通过。源码中未提前加入相邻4169/416c/4170；其只读审计不能证明实际执行。

第二轮新拒绝是 `400f/type5/12B`，wire `05000f403b00008002040000`。原handler0x354d50为 `SET_EZOOM_ON`，按word/byte/byte写入+b10/+b14/+b15，三字段各取原请求byte8/9/10；apply-control0保留dirty。此命令表的checker0x35db28已另核：比较旧参数只调用debug日志，不拒绝、不修改状态。dispatcher0x35cf70确认source80020002时调用checker后仍调用handler并按表设置共同dirty。原AP构造0x3541a54的type5、12B、SID90030001均相符。已实现六字节精确写入、邻接未知状态保留和原请求free，实际wire与原有256值/错误/生命周期测试已通过；第三轮独立运行中。

源码修改前像及完整摘要在本轮 `manifest.json` / `restore/`，4167已验收而414a尚未加入时的第二恢复点在 `family-manifest.json` / `family-restore/`。恢复须反向应用本轮精确差异，保留用户已有未提交修改。原失败、源码前像、当前binding及运行输出保留给父会话核收和下一前沿调查。生成前空间门禁为可用不少于64GiB余量加12GiB新增峰值，已通过；最终实占与可用量由本轮 `storage.json` 记录。本轮未执行回收。
