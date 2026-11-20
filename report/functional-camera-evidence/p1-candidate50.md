# P1/P4 candidate50：统一集成与首轮预启动失败

## 集成范围

- `0x40df` 按原 CP handler 写五字段并返回同步 `type1/40df/token/f000` ACK；与 `3007` 回复观察器隔离。
- model `0x17c`：原启动门、实际 maps/base/TTBR0 和同一 GDB owner 的只读硬件断点接入 RAM 卡路线；未直接清门。
- 原 POWER 输入、正常关机序列、Backup/设置证据与退出门接入。
- 独立内部持久盘 + 1GiB RAM 拍摄卡组合及第二新 QEMU 启动接入。
- P4：自然请求闭合、quit 前双整卡导出、本轮 manifest、生产 batch 与 JPEG checker 顺序接入。

## 构建与统一宿主验收

主会话实际重建 observer、基础 initramfs 和 RAM 卡 CPIO：

- observer `4e5f70c32a2ead1331fbac098a69cd8d4c09a5a66f0fe4c79a54346b3b283e06`；
- 基础 CPIO `805a498bbd12d8bf21f1560186267306bf9ace21d36aeb354fb2a926f9b93978`；
- derive `derive-prod-94606a2bde956025`，RAM CPIO `3762d69d314ac84bd0468d275394f4907ea9c5eca5230ac5d26cc5a7f5a2b826`；
- QEMU 保持 `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad`。

统一两线程、两组最终收据：`acceptance-5/host-summary.json`。5,652 项测试，0 失败、0 错误、9 项明确跳过；2,502 个源文件前后摘要一致。该结果是选定宿主检查，不是完整业务验收。前几轮失败与集中修复原样保留在 `acceptance-1` 至 `acceptance-4`、`FIX.md` 和产品修复专题中。

## 首轮运行结果

`runtime-1/result.json` / `failure.json`：组合 derive 把输出放到候选 scratch，`functional_ram_initramfs.project_path` 正确拒绝产品外输入/输出，故在启动前失败，`attempts=[]`，未启动 QEMU，未写卡，未发信号。

主会话随后把组合 derive 输出改到产品既有 `functional-camera-profiles/settings-restart-*` 受管目录，并创建不含旧收据的 candidate51 运行副本。首轮失败没有回填为通过。

## 状态

`selected_checks_verified=true` 仅对应上述宿主范围；`verified=false`、`capture_verified=false`、`installation_verified=false`、`physical_compatible=false`。实际自然4038、JPEG、写卡、正常关机、双启动及 P4 仍由后续实跑核定。
