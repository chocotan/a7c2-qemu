# CP4001：共享四字段事务与 idle oneway owner

`type5/4001` 已实现 source-closed 的本机配置消费和独立原请求 free 生命周期。数据层在 main 的同一个 `cp_parameter_state` 上执行四个 unsigned-byte 输入、十个实际 image 字节的事务写入，并逐范围读回。tiny transport owner 本轮只接受 `drive=0/trigger=0` 的 idle 子集；两个 speed byte 原样保存。成功路径只执行一次原 free，`oneway_consumed` 在它返回 0 后才为 1。代码没有 ACK allocation/send、common APPLY、generation 增量或发布动作。

主会话已接入原 AP send、retained-free hook 和构建脚本，当前仍待该批完整构建、双ABI和新VM验收。原 metadata Zoom 的物理行为、光学运动、EE、mode1 和拍摄均未因这些 host 测试得到验证。`8000004c` 是 wire caller；metadata source 仍严格为 `80020002`。原 AP 是否阻塞在此请求仍是候选，不能声称该 free 解除了所有 EE 阻塞。

范围与授权见 [scope.md](scope.md)。`flavor=null`，severity=`n/a_re`。

## 主会话接入

代码位于 `../../runtime/analysis/device-models/`，稳定接口为 [cp-parameter-state.h](../../runtime/analysis/device-models/cp-parameter-state.h) 和 [functional-cp-zoom.h](../../runtime/analysis/device-models/functional-cp-zoom.h)。

1. 在既有 `cp_owned_parameters` 初始化后调用 `functional_cp_zoom_owner_init(&cp_owned_parameters)`。它只绑定真实共享数据 owner，不初始化参数、不启动 broker、不运行 RPC。实际 4001 消费要求该 owner 已执行 common stores、bootstrap/default stores 和 bulk4063。
2. 在现有 functional profile 的原 send 路径提供 `full_imaging_io`、既有 `native_cp_state_publication_guard` 及 main 构造的 `cp_start_state_guard`。资源 guard 必须覆盖与 common/bootstrap/bulk 及其它参数消费者相同的序列化区域；`predecessor_ready` 必须读取实际同进程前驱消费。data guard 必须是同 PID、同 origin、quiescent=1、相等偶数 before/after。
3. 调用 `functional_cp_zoom_dispatch(destination, original_request, &io, &resource_guard, &data_guard, enabled, &result)`。其它 type/opcode 返回 handled=0；可识别 4001 的 shape/provenance/data/guard 错误为 handled=1/result<0，原请求仍归 caller。输入/输出或 callback 结构 alias 在数据消费与原 free 之前拒绝；这种调用契约错误可返回 handled=0。
4. 数据事务成功后 result=0 表示请求已由此 owner 接管，包括后续读回/包不变性检查或原 free 失败。必须检查 snapshot：`config_consumed=1` 只证明数据写入；`oneway_consumed=1` 还要求实际原 free 成功。失败保留 `retained_request`、sticky `faults`，不会重试原 free，也不能回退给另一个 owner 重用。
5. 原 free hook 可先询问 `functional_cp_zoom_release`，阻止对仍保留的 owned original pointer 再次 free。它不执行新 free；成功退休后的诊断地址不再认领后续 OSAL 对象，即使地址相同也返回0。**不要为 4001 allocate/send completion、F000 或 F001。** F001 只属于原 support-disabled 分支。

主会话后续完善支持每个真正新的 idle 事件：source sequence 必须严格前进；相同序列由共享 helper 返回 `-EALREADY`，更旧序列拒绝。成功free0后可更换caller、复用同一地址，不重复消耗旧请求；free失败仍保留/锁死当前owned指针。guard按 **DMM→共享parameter mutex** 获取、逆序释放；source偶数序列是本地接收事务票据，不能当作原CP generation。51个owner场景各strict/SAN与数据/source检查共6项通过，包含重复两事件、速度变更、同地址foreign消息及旧序列拒绝；实际main绑定/锁顺序另有C提取测试。

main 已在 `menu-observe.c` 完成同一个参数owner的lazy绑定、正确metadata source/独立caller校验、原oneway send及retained-free接线，并将模块加入build/统一冻结；完整构建、双ABI与原VM仍由后续整批执行。

## 数据 API 与实际写入

`cp_parameter_state_consume_zoom(owner, guard, metadata_source, target, input, size, out)` 要求 12B、type5、cmd4001、非零 opaque caller、metadata source80020002、target90030001。caller 不充当 transport source；header+1 和 caller 原样保存在 `out.wire`。helper 不夹值、不拆位域、不做符号扩展，接受所有 u8 输入。

| 原 body | 实际 image | 宽度 | seq60 输入 | 逐字段读回 |
|---|---|---:|---:|---|
| +0 drive | P+69c | 4 | 00 | 00000000 |
| +1 speed | P+698 | 1 | 02 | 02 |
| +2 trigger | P+6a0 | 4 | 00 | 00000000 |
| +3 movie speed | P+6a4 | 1 | 02 | 02 |

四条 descriptor 与 bulk4063 复用同一个内部 `apply_fields`。四字段先写到 owner 的本地事务副本，再调用既有 `cp_parameter_state_read` 逐范围读回，核验十个 known bit 和精确字节后整体提交。`read_zoom` 重新读取实际 image；未知字节返回 ENODATA，已被其它写入改变的值返回 ESTALE。两者所有错误都保持 owner/output 原值。

`out.fields` 按 drive/u32、speed/u8、trigger/u32、movie/u8 排列，实际包为 `00000000020000000002`，`known_mask=03ff`。这不是把 698..6a5 整块区域初始化：699..69b 的旧值和 unknownness 保持。`out.count/config_consumed` 与 batch 的 config/semantic masks 分开；原 4063 wire、固定 190 slots、303 条 bulk field descriptors、batch masks 和 P+d5c 均保持原值。已有独立 parameter view 不会被静默刷新。

同 PID 校验使用 owner 的实际 batch PID；guard 的 PID、origin、before/after、偶数性、quiescence、输入/输出/owner/guard 全 span wrap、alignment 和 overlap 均在提交前校验。重复 sequence 拒绝，后续数据写入须严格递增；读回允许同 origin 的较新 guard。初始化只产生 unknown image，common/default markers 仅由对应源消费函数置位。

## 原来源与 oneway 合同

[source-pins.json](source-pins.json) 保留原 source 调查的完整 AP/CP 身份、8 个字节窗口、raw/VA/SHA、实际 seq60 audit/chunk 和 claim 边界；[cp4001-fields.inc](cp4001-fields.inc) 保留独立四 descriptor。公开原件由读者本地准备，不随本目录发布。

实际第四次 `run-q2w2q6v8`：pid258/tid403/seq60，metadata source80020002 → target90030001，原 wire=`050001404c00008000020002`，caller=`8000004c`。packet SHA256=`dfee4a309b43d455998020c2e4af02bacd97f7ee19c2d8481b5b39dfa89e67d7`。这些是历史输入身份；本地测试日志中的 PID/TID 来自运行测试的真实主机进程，不伪装成该原 AP worker。

原 AP3545064 通过 executor output=NULL 跳过 future completion wait。CP4001 support enable=1、apply-control=1；正常四次 store 后 receive loop free 原请求，没有成功 ACK、公共 APPLY、generation++ 或 bank publication。本实现保留这个数据和生命周期边界，speed code2 不被换算成物理速率，idle 不修改主机场景焦距，也没有新增 model operation。

## 验证

从本成果目录执行：

```bash
python3 -m pytest runtime/analysis/test_functional_cp_zoom.py runtime/analysis/test_cp_parameter_state.py runtime/analysis/test_cp_parameter_batch.py runtime/analysis/test_cp_parameter_view.py --color=no -q
```

初始交付为42项通过。`verification.json` 与 `artifact-hashes.json` 保留该初始限定实现的历史记录，不是后续重复生命周期改动的当前源码摘要；当前权威源码闭包以新的统一批次 `inputs.json`/归档/ready为准。新增的6项当时包含 strict C11/Wall/Wextra/Werror/pedantic normal 与 ASan/UBSan 两套运行、50个owner场景和共享数据域检查；原 state/batch/view 的36项同时通过。详见 [verification.json](verification.json)。

覆盖实际单 4001 的四值读回、u32 高字节清零、所有 u8 输入、未知间隙、旧 batch wire/190 masks、错误 size/type/cmd/source/caller、缺失 common/bootstrap/bulk、guard/torn/PID/origin/fork/alias、包/metadata 变化、原 free 失败、接管后失败、重复 dispatch/free、重入及 callback 内 fork。allocate/send/set-source 回调是会立即断言失败的 traps，成功不依赖 ACK。日志核验原 12B、独立 source/caller、FNV、四字段 offsets/width/readback/knownmask、真实线程、原 free、count、来源以及 applied0/published0/generation0/capture0。

这些是 host model/ownership 证据。没有运行全仓回归、DSO build、双 ABI 构建或 VM，没有触及真机、真实 SD 或私有 dump。原 source pins 内 `native_config_consumed=false` 描述历史 native 运行，不能因为 host C 测试而改成 true。

## Evidence → Finding → Path

| E-id | source_ref / content_hash | repro_command / 观察 |
|---|---|---|
| E-source | source-pins.json，文件 SHA 见 artifact-hashes.json | 上述 pytest 的 pin test 校验公开 AP/CP 完整 SHA 与全部窗口；4001 handler 四次 unsigned-byte load/store，enabled normal 分支无 ACK/common APPLY |
| E-wire | source-pins.json actual；packet SHA 如上 | pin test 独立核对 12B、caller 与 metadata source；原 tid403 只证明异步 API entry |
| E-data | cp-parameter-state.c、test-cp-parameter-state.c；SHA 见 artifact-hashes.json | strict/SAN 全 byte 域和边界，四字段原子提交/真实读回；不修改 batch wire/masks、unknown gaps 或 generation |
| E-owner | functional-cp-zoom.c、test-functional-cp-zoom.c；SHA 见 artifact-hashes.json | strict/SAN 50 场景，真实测试 callback free 次数为一次；失败 retained/sticky fault，ACK traps 不触发 |

| F-id | severity / status / confidence | evidence_ids / location / 含义 |
|---|---|---|
| F-data | n/a_re / validated-host / high | E-source,E-data；CP354768 与 consume_zoom；数据模型忠实保存四个 u8 和十个实际 image 字节 |
| F-oneway | n/a_re / validated-host / high | E-source,E-owner；AP3545064/CP35cf70；原正常 free 语义被独立消费，无 ACK 或 publication claim |
| F-native | n/a_re / unresolved / high confidence in limitation | E-wire,E-owner；只有历史 audit 与 host callbacks，原 AP send 返回/原 CP 消费、物理 Zoom、EE 或 capture 未验证 |

P-001，`path_type=callflow`：原 AP wrapper/metadata source → 原 12B send（E-wire/F-native）→ main guard 与同一个参数 owner → 共享四字段事务/读回（E-source,E-data/F-data）→ 一次原 free → oneway_consumed（E-source,E-owner/F-oneway）。本次只验证这个路径的 host 实现；native 接线和端到端路径由主会话接续。

Timeline：读取根/final 约定和既有 pins → 固定两个头文件 → 抽取共享 field helper、实现数据事务 → 实现 tiny idle/free owner → strict/SAN 与原批量/视图测试 → 固化报告与 hashes。没有重做 source 反编译，也没有把原请求最后出现的位置提升为当前 blocker。
