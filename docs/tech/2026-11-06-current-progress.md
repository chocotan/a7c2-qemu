# 2026-11-06 研究进展：完整离线验收通过，原固件QEMU运行仍停在下一笔发送

**完整离线 cohort 已实际通过：22,952 tests／20,213 subtests，0 failure／error／skip。原固件QEMU运行在晚期 4000（OP22）之后完成 4057，下一笔 4072 发送断言失败，UI1 以 FirmwareFault 结束；卡上没有 JPEG／MP4。** `capture_verified=false`，物理 ASIC 兼容性独立未验证。

本次只发布文档。公开仓运行源码保持 10 月 31 日移交版本（当前公开 main `d6fb503`），以下研究结果没有自动移植到本包；本次 checkout 不含 OP20／21／22／23 的最新实现，也不能直接复现研究侧的 22,952 项测试。旧公开 shutter-gate 源码发布继续保留。

## 最新结果

| 项目 | 实际结果 | 边界 |
|---|---|---|
| 新完整离线 cohort `vxju27_y` | `PASS_OFFLINE_SHUTTER_GATE_V2_COHORT`，rc0；**22,952 tests／20,213 subtests**；JUnit 43,165 tests、0 failure／error／skip；1,388 sources／277 modules | 离线 cohort；原 VM、原卡、guest、intent 均未启动 |
| 四个 gate 阶段 | unified-camera、shutter-gate-actualapi、shutter-gate-v2-actualapi、readback 均 rc0；父验收为 `PASS_OFFLINE_SHUTTER_GATE_V2_COHORT_READBACK` | 双原 ABI、dual actualAPI v2／v3 合同与 gate v1／v2 合同均通过；不代替原固件QEMU运行 |
| 原 3dgq 完整批 | **FAIL 保留**：21,557／20,131，14 failure／1,390 error／0 skip，1,396 个失败节点；74 个原件／33,769,360 B 已保全 | 失败批次永久拒绝被借作新完成结果 |
| 必要失败项复查 | **PASS**：1,431 tests／1,698 subtests，0 failure／error／skip；相对原失败冻源仅 3 个根修文件 | 只关闭原失败节点及其直接依赖，不等于完整批通过 |
| 模型与源 | 25 成员；新库 `14941e64ce5c48e28f3889c8748f7b4519f7986de183b87d988f6241c4a59cd5` ≠ 旧库 `9834c57b9515eff0486b6afe283a5860e5ace20b9515026064a8619c80a93471`；仅 Core C/H 与 ABI 3 个成员变化；源 1,388／277，相对 R8 为 32 changed + 2 added | 新原 AP 成片未因此通过 |
| Once／source 工具 | generator 首次 rc1；31 文件／3,337,264 B 原失败保全；1 文件精确 2 处 WORK 字面量修正后 derive rc0；5 个 guard 用例通过 | 只放宽已审阅的精确迁移，其它 AST 不变 |
| actualpure | `PASS_MOCK_ONLY`：1,897 cases = 340 inherited + 1,557 v2；旧 1,728 全集身份保留 | 仅 mock 自检，不是原 AP 通过 |
| 原固件QEMU运行 `run-ehgdk5qp` | 晚期 OP22 返回 240 B、config 24→25；4057 完成；下一 4072 发送断言失败；UI1 rc1／FirmwareFault | 无 JPEG／MP4；正式全图仍 FAIL |

离线 operand 读回为 `PARENT_ACTUAL_NEW_COHORT_OFFLINE_OPERAND_READER_COMPATIBILITY_PASS_NO_RUN`：1,725 files／398,103,274 B；`original_Sony_VM_started=false`。它只说明离线 reader 兼容，不说明原 AP 已消费 OP22。

## 这一次原固件在QEMU走到哪里

| 原请求 | 实际内容 | 结果 |
|---|---|---|
| 参数 bank 4063 | 2,564 B；Core 2,756；独立读回与原生 receipt 一致 | config 22→23；实际 request free |
| 晚期 409d | 12 B；Core 208；getter 与 receipt 一致 | config 23→24；原 receive／sender 双 free |
| 晚期 4000（OP22） | seq 51；Core 240＝returned 240＝getter 240＝native receipt 240；原输入 20 B | config 24→25；frame 22／媒体计数不变，不产生图像 |
| 后续 4057（OP14） | seq 54；sender 384／receiver 356；request／reply free 均 0，AP_consumed 1 | 当前 functional startup 配置完成 |
| 下一 4072 | audit 140 完整原输入与异常活动栈前 12 B 逐字相等；14 个 FP 链接 | 在 `osal_snd_msg` 后对发送结果判零，进入非零断言；未进入自身模型消费 |

4000 的原输入为 `0500004061000080050100000000000000000100`，独立回复为 `010000406100008000f00000`。完整 C 输出缓冲 65,024 B，前 240 B 为 receipt，其余 64,784 B 全零。STATE 只有 config generation 的 8 B 字段改变；frame 22、rendered 22、consumed 21 保持，JPEG／video 编码计数均为 0。movie 家族 12 个 EVENT（各 106 字段）、6 个 BYTES（各 19 字段）和 resource35 三标签均核对；receiver 在 send inflight 时实际接收，sender 实际释放请求与回复，最终 complete 1、两份 retained 均 nil。

4072 的 wire 为 `050072406100008000000000`，type 5／4072／12 B。关键原调用点为 `33a1fe4 → 34cbbb0 → 3545700 → 3535a64(osal_snd_msg) → 3535af4(assert)`；保存的原字节显示 `3535a68` 对 send 结果判零。该 opcode 本身是单向，无 reply／ACK；旧 strict 4072 one-shot 已经用过。源码推导返回 **-1023**，但运行没有直接打印该数字，`runtime_numeric_send_rc=null`；附近 UIPC warning 和旧 4000 的返回值都不能用来填补。

## 本次失败／保留项

- **原 UI1 与正式全图仍失败**：UI1 rc1／FirmwareFault；未改的 strict reader 对真实闭合输入返回 `FAIL／EVIDENCE_INVALID／guest entered exception monitor`。本轮控制内容的有限通过不回填这两项。
- **两处正式 movie 工具缺陷**：原 manifest 与 backup 子表缺少全部 13 个 `functional_camera_cp_movie_format_*` 声明，正式 movie 顶层 checker 拒绝；`cp_movie_format_initial_history()` 按同 tag 收集 strict EE reply-free 时混入后续 opcode 3012，完整日志下拒绝。只建立排除该无关 3012 行的输入视图，保留原行和完整输入拒绝；有限内容正例不能提升为正式全图通过。
- **Once generator 首次失败**：完整批 PASS 后 generator rc1，原因是 `validate_plan`／`create_plan` 的 WORK 目录字面量迁移不在 AST 白名单；失败在准备阶段，没有 staged Once、work、guest／card／intent 或原 VM。原 31 文件失败已保全。
- **资源 prewrite 拒绝**：首次八阶段续接在 `install-tested-guest-observer` 的 `prepare.no_project_qemu()` 以“已有活动系统 QEMU”拒绝；拒绝发生在 backup、首次 target write、guest、card、nonce、intent 之前，QMP 0、signal 0。该 PID 之后消失，身份无法再确认；父会话在独立目录续接六个未用阶段，安装和资源准备通过，原AP运行形成本文的 EHG 失败记录。早期拒绝原件保留。
- **3dgq 失败不回填**：1,396 个失败节点、原 JUnit 计数、无 ready／原 VM 事实均保持；必要复查的 1,431／1,698 只覆盖这些节点及直接依赖。

## 收尾与资源

actual CANCEL event 1341 返回 C0／128 B，随后 detach 1342、mailbox 1344、debugger 1345、cleanup 1346 均确认。父会话核对 QEMU 身份后仅请求一次正常 QMP quit，收到 ACK 并通过 pidfd 确认退出，QEMU 信号 0；专属 GUI 正常 close，专属 Xvfb 只发 TERM，无 SIGKILL。

未改的 strict postexit 返回 0，独立读回 297 份 raw、1,083 份 run 文件／602,166,521 B；虚拟卡 2 文件，media 列表为空，卡前后摘要相同；7 项已知 owner 均消失；两个既存锁排他，第二次 open 被拒。保全 SHA 为 `bd934ffecfab82d3e814eb2981a7c8272cf5692aa64247e1ead6ba112af1a78f`。本轮 guest、卡、plan／intent、run 与所用 VXJU batch 均已消费，下一运行必须使用全新代次，不能复用旧资源。

## 下一步

4072 之后需要一个独立晚期 one-way OU-crank 功能事务（OP23，12 B→224 B，resource36 + metadata）：只接受已观测零 body、显式消费原 12 B、独立读回当前软件配置，保留真实 sender request free，不重置旧 attempts，也不添加 ACK／receive 模型。改动涉及 formal、Main 与资源/元数据层。

该实现正在完成源码接线，**尚未完成集中测试或新原AP验收**；使用显式功能 profile `virtual-functional-camera-v1`，默认关闭，原 strict owner／attempt 不重置。新模型与 source build 都还没有验证，不能据此写新的原 AP 通过。公开摘要不追活动候选的可变摘要。

## 边界与证据

本次文档不包含新的运行测试或媒体解码；研究原运行均使用隔离本机QEMU，未接真机。研究权威来源为 `a7c2-re` 的 `report/2026-10-17-qemu-native-camera/`；完整离线结论见 `report/2026-11-06-jky-late4000-full-cohort-vxju/README.md`（11,933 B，SHA-256 `4276fdfbcf590857df1e79f9d6aa642fddf5e924d3a7bde9a139873c1010a326`）与 `validation.json`（9,558 B，SHA-256 `ba9bbc2d3ec297eeebdf0766921edbaa4c9dbb316d9dc962865ced177e84a5a6`）；原固件QEMU运行见 `report/2026-11-06-native-shutter-ehg/README.md`（6,131 B，SHA-256 `edd4ba2368ea21fb0e5ac8e370de640240ed8d6a4bda226193fe25e73b3c8f5e`）与 `validation.json`（4,586 B，SHA-256 `d606c8f497f1089af4b872e18075c1c4d0248bcffc1809acd1c9757891a8fe25`）。这些是研究项目内路径，不随公开包分发，也不能当作公开 checkouts 可下载的链接。

`capture_verified=false`、`physical_asic_compatibility_verified=false`、`minimal_business_patch=null`；没有 JPEG／MP4，没有原 AP 对 OP22／OP23 的成片消费结论。功能 profile 的字段与成功只属于本机软件功能模型，不代表 Sony 物理 ASIC 格式、CP RAM／RTOS 或历史兼容性。固件、私有设置、虚拟卡、guest、完整日志和原始运行证据均不进入公开包。

| Evidence | Finding | Path |
|---|---|---|
| 完整离线 cohort、必要复查与源审查 | 离线验收通过；原 3dgq 失败保留 | [进度 JSON](../../validation/2026-11-06-progress.json) → 研究源摘要 |
| 原固件QEMU 4063／409d／4000／4057／4072 与关闭 | 控制内容到 OP22 有限通过；4072 发送失败；无媒体 | [发布说明](../../report/2026-11-06-documentation-publication/README.md) → EHG 摘要 |
| 公开源码与检查范围 | 本次仅文档；公开代码保持 `d6fb503` | [验证记录](../../validation/README.md) |
