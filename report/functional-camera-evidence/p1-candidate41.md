# P1 第四十一跑：face index6 实际接线与拍摄参数接收

本轮把已存在的 face type2/index6 处理器接入它的真实目的地 `0x90060197`。首轮 `7ddb` 已证明原 AP 命中正确调用点、DMM 列表消费和原请求释放成功；新的首个负发送为 `0x4083`。第二轮 `fb70` 实际接收其 object tracking mode 参数，原请求free0，随后推进到 `0x4048`。本轮又按原 handler 补上该曝光补偿参数并建立独立第三轮。EE RUNNING、自然快门、4038、JPEG 和写卡尚未验收，`capture_verified=false`。

范围为用户授权的隔离 QEMU、独立 RAM 卡和原 App32 输入。没有操作真实设备，没有修改 EE、exclusion、镜头或快门状态；按用户要求跳过镜头伸出调查。本轮未继续委派。此路线仍为 direct-bootin 诊断，不执行 Sony loader/WBI 恢复、真实 CP 或物理看门狗。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| candidate40/runtime-2 的 `784b` 原失败与本轮源码前像 | index6 handler 存在，但只在 DMM `0x9061003c` 分支调用；实际 face SID 只调用 index7 receiver | 原 AP type2/index6 → `0x90060197` → 未路由 → −1020 |
| candidate41/runtime-1，`7ddb` 的 SOURCE_BOUND 原日志 | 实际 `appFw.so` 基址 `0x7f2b0b1000`，caller `0x7f2e5e6a68`，差值 `0x3535a68`；caller−4 指令两读均 `0x9784a41b`、source `0x80020002`、rc0 | 原 AP → 原发送 hook 的返回地址 → 已有原调用点校验 → face list dispatcher |
| 同 run 的 NATIVE_CP_FACE_LIST 与 final-verification.json | generation1/retired1/free0；unit1db 的 handle8404、epoch3、reference11、53504 字节 backing 身份有效 | 原 DMM share 生命期 → index6 → 内部0e00存储 → 原请求free；event2c仍pending、completion0 |
| 同 run 的 P18_OSAL_RESULT 与 4083-audit.json | 下个首个拒绝为 source80020002、type5、4083、12B；原 CP handler0x35482c写参数根+bd1，值2另调用0x7ec50e | 原 AP → object tracking mode → CP参数写入；值2另依赖face后端 |
| fb70 的实际4083接收/free0、新4048负发送与4048-audit.json | 原 CP handler0x3551a8依次写+2c0字节、+2c4四字节、+2bf字节，原表控制字0需要保留apply dirty | 原 AP SET_EXPOSURE_BIAS → 12B参数 → 三字段写入 → pending apply；不新增完成ACK |

旧 `P18_OSAL_RESULT` 中的 caller 可能属于观察器调用原 sender 的内部位置，不能单独作为 AP 基址证据；本轮使用 SOURCE_BOUND 的真实动态库绑定、返回地址和指令读回。此前 `784b` 的失败现场保持不变。

## 修改与边界

- 在 face SID 的现有 profile 分支内，先调用 `native_functional_face_send`，未匹配的请求继续走 `native_cp_background_dispatch`。index6 的24B/type2/index6才进入列表；index7的12B继续走既有接收器。
- 保留实际调用点、原指令、source、长度、DMM owner/epoch/reference、backing及释放校验。没有建立通用 ACK，没有改 AP 状态来绕过门禁。
- `0x4083` 复用参数 owner：存 request[8] 到 offset0xbd1、宽度1；原表控制字1对应不新增 apply dirty。保留所有未触及字节的未知状态和已有 pending。
- `0x4048` 复用同一 owner 写原来的 byte/word/byte 字段；有符号bias在原handler中最终按字节存储，因此保留原始8位值，不把它扩成word。只标记实际写过的六个字节为已知，保留邻接未知字节；继续保留apply pending。
- **4083值2尚未实现**：原 handler 此时另外调用 face 后端。本实现于任何状态修改和请求释放前明确拒绝该值；没有将缺失副作用记成完成。本次实际运行请求值为0。测试遍历全部256值，确认255值按原单字节语义接收，值2不变更状态且请求仍归调用者。

## 检查与运行

首轮两个检查组、两个线程：face runtime 60项，face receiver/接线2项通过。扩展构建同样使用两个组、两个线程：CP参数/旧owner回归2项及22子测试通过，face receiver/接线2项通过；参数入口内部另执行全部opcode、值域、错误来源/尺寸、free失败、重入和fork用例。沿用已登记的公开测试入口，没有新增依赖。

两轮均重建 observer、保持CPIO成员及权限，只允许 `simulation/menu-observe.so` 内容变化，然后执行正式 `functional_ram_initramfs.derive` 并绑定输出摘要。第一轮 guest OpenSSL 实读 observer SHA256 为 `608ab27875ed2d8b886556c697fdebe48cff2136b82bad452e8e91bc0a4bc890`。

首轮 `7ddb` 已完成两线程、两检查组独立核收：两笔原 UPM 生命周期、all13 accepted、broker attach、唯一ID QMP quit、QEMU rc0、无信号、debugger detach、owner关闭及租约到退出；83个归档文件完整SHA256与原run相同。UPM watcher 未复现重复key问题，因此未修改其约束。**运行本身仍为 FirmwareFault 失败**，局部核收通过只代表 index6 接管及资源/证据闭合。

首次核收脚本错误使用 `SHA256` 标签，guest实际为 `SHA2-256`，导致检查失败；原stdout/stderr保留，修正匹配后独立 `finalize-v2` 核收，不把该检查错误算作 guest 故障。

第二轮独立 `fb70` 使用 `integration-extension` 的新binding。原 AP 实际4083接收记录为generation28、offset0xbd1、width1、value0、apply_marked0、request_free_rc0、handler_executed1；下个首个负发送为4048，wire `050048402a00008000010100`，随后仍发生原 FirmwareFault。两笔UPM、all13/broker、正常quit/rc0、无信号、detach及租约到退出核收通过；85个归档文件完整摘要一致，见 `final-verification-extension.json`。第三轮使用 `integration-exposure`；其结果待独立核收，不预先声明4048运行消费、EE完成或拍摄通过。

## 复现、恢复和材料

工程根入口为本轮受管目录 `scratch/a7c2-capture-p1-runtime-20261115-candidate41/` 内的 `prepare.py`、`integrate.py`、`start.py`，4083扩展入口为 `prepare-extension.py`、`audit-4083.py`、`integrate-extension.py`、`start-extension.py`。脚本先审查再执行；所有入口产生一次性收据，已有输出目录不能原地覆盖重跑。TMPDIR设置为本轮 `tmp/`；宿主/guest显式启用同一functional profile。

源码前像及完整摘要在 `manifest.json`/`restore/` 与 `extension-manifest.json`/`extension-restore/`。恢复须逐文件反向应用本轮差异，保留用户原有未提交修改；不覆盖整个工作树。原输出、失败收据和大产物只保留在受管scratch/runtime目录，公开报告仅引用路径、摘要和必要小型证据。

空间、进程与租约账本为同目录 `storage.json`；生成前64GiB余量门禁通过。原失败现场、当前derive和复核材料保留给父会话的证据核收、恢复和下一前沿调查；本轮未执行回收。最终新增实占和文件系统可用量以收尾账本为准。
