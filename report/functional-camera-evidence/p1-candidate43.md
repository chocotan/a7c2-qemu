# P1 第四十三跑：4147 参数接收与 400f 实际消费

本轮按原 CP handler 为 `0x4147` 补入既有参数 owner，目标是让原 AP 继续走 EE 初始化、自然快门和 JPEG 生命周期。4147、40d3、4151实现及宿主检查通过，原AP实际消费/free0分别获独立运行核收，400f亦获首次运行消费验证；尚无完整拍摄证据，`capture_verified=false`。不改 AP 状态、EE、exclusion 或镜头状态，不用构造成功回复跳过原调用链。

范围为用户已授权的独立本机 QEMU、RAM 卡和原 App32 输入。沿用 candidate42/runtime-3 的 direct-bootin 诊断入口，不能替代原 Sony loader/WBI、真实 CP、物理看门狗或实机拍摄。镜头线按用户指示跳过。本轮不再委派。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| candidate42/runtime-3 原失败，wire `050047413700008001000000` | destination90030001、source80020002、type5、4147、12B 返回−1020 | 原 AP → CP 参数 SID → 缺失参数合同 → Imaging3109 |
| `4147-audit.json` 与 `4147-audit.stdout` | CP handler0x35bdec：ldrb request+8、str.w 参数+0x19c；表apply-control0；其余分支仅debug日志 | byte零扩展word写入 → 共同dirty义务 → 释放原请求，不增加ACK |
| `ap-4147-audit.json` 与 stdout | AP构造0x3542610–0x354269c：type5、opcode4147、12B，发送至90030001 | 原请求构造和原sender → 既有owner，保持原返回/错误处理 |
| `integration/host-validation.json`、原stdout/stderr | 两组、两线程宿主检查通过；参数2项/22子场景及face接收回归通过 | 已登记 test_cp_opcode_batch.py → sanitizer合同检查 → observer、CPIO、生产derive |

CP 输入 SHA256：`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。AP 输入 SHA256：`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。原输入只读，不把原固件或批量运行输出加入公开报告。

## 实现和复现

生产改动在 `runtime/analysis/device-models/cp-background-device.c` 追加 `4147/12B/+0x19c/word/STORE_BYTE`，首轮揭示新前沿后追加 `40d3/12B/+0xb24/word/STORE_BYTE`，随后重试揭示的4151按原handler补七字段写入。现有 owner 的来源、尺寸、重入、故障锁存、free和fork守卫保持。只把实际写入的四字节标为已知，邻接未知值不填造，apply_pending不等于原CP apply完成。

测试复用已登记的 `runtime/analysis/test_cp_opcode_batch.py`，加入4147的256值、错误来源/尺寸、free失败、重入、fork与完整opcode场景，另用原失败wire核四字节零扩展、邻接未知和原请求释放。`400f`实现继承自第42跑，本轮要求真实运行消费后再记通过。

受管任务目录为 `scratch/a7c2-capture-p1-runtime-20261115-candidate43/`。`prepare.py`先保存当前源码前像、完整摘要、空间预算和已闭合前序运行身份；`start.py`执行 `integrate.py`，再由独立所有者调用 `runtime-1/start.py --supervise`。脚本均先读后执行，TMPDIR显式位于本轮目录。每轮CPIO成员和权限保持，只有 `simulation/menu-observe.so` 内容可变；正式derive与运行driver通过完整SHA绑定。

恢复前像在本轮 `manifest.json` / `restore/`。恢复需按精确差异反向应用，保留其他已存在的未提交修改。原失败收据保持，不回填。

## 运行与资源

第一轮 `05a0` 已完整闭合：原 AP 实际消费4147（generation32、参数+0x19c、word值1、free0）及400f（generation34、free0）。`final-verification-1.json` 两组两线程核收通过；原UPM两笔、all13 accepted、broker attach、guest observer SHA256 `bf21e73b481f59a10c3b829b32f4fc64804fb0cab302b6cf6cdd9910297703d7`、归档完整读回、detach、唯一ID QMP quit、QEMU rc0、无信号和租约到退出均闭合。原运行仍以 FirmwareFault 失败，不把资源/参数核收当作拍摄通过。首次宿主finalize因观察脚本名inspect.py遮蔽Python标准库而失败，原stdout/stderr保留；改名watch-run.py后重新核收，未修改guest和原运行证据。

首轮新首个负发送为40d3/type5/12B，wire `0500d3404000008000000000`，destination90030001、source80020002、rc−1020。`40d3-audit.json`确认CP handler0x3597fc：request[8]零扩展写参数word+0xb24，apply-control0，其余仅debug日志。AP构造0x353ac2c–0x353aca0的type5、12B、SID相符。已加入既有STORE_BYTE owner及登记测试。第一恢复点 `family-manifest.json` / `family-restore/`保留仅4147已验收状态。第二轮 `e877` 在首设第32阶段提前失败，未到40d3：原302c all13 readback为accepted0，HDMI audio第十笔AP free/cold-Get未就绪，继而Imaging3109。`failed-run-2-review.json` 两组两线程确认原失败、归档完整摘要及quit/rc0/无信号/租约和runner关闭；不把它记为40d3失败或通过。`retry.py`以相同derive、同driver和动作文件（逐文件SHA比对）启动唯一独立重试 `runtime-2-retry/`，没有重建未变化产物，没有修改all13或guest状态。重试需40d3真实消费收据再记通过，首败收据保留不回填。

唯一重试 `1db6` 已确认40d3 generation34、word+0xb24=0、free0，400f generation33亦有原消费/free0；原all13最终accepted1、UPM两笔/broker、guest摘要、归档和quit/rc0/无信号闭合，见 `final-verification-2-retry.json`。该轮未发送4147，覆盖字段明确为false；4147通过依据仍只取第一轮，不把跨轮收据混成一次运行。

重试新前沿4151/type5/24B，wire `050051413f0000801e000000010000000100000001000100`，destination90030001、source80020002、rc−1020。原CP handler0x8db508把request的+8/+12/+14/+16/+20/+22/+23分别按4/2/1/4/2/1/1字节读取，写入参数+3e8/+3ec/+3f0/+3f4/+3f8/+3fc/+400，写宽4/2/4/4/2/4/4；apply-control0，其余仅debug日志，无额外后端。AP构造0x353dd04–0x353dd8c确认同SID、type5、24B。已在同一owner中补精确七字段写入，未初始化+3ee/+3ef/+3fa/+3fb间隙。实际wire、256值（含高位与字节/半字零扩展）、邻接未知、错误尺寸/来源和生命周期测试加入同一登记入口。第二阶段恢复点在 `stage-2-manifest.json` / `stage-2-restore/`。第三轮 `70b8` 已确认4151 generation35、24B、free0，同时400f generation33、40d3 generation34消费。`final-verification-3.json`两组两线程通过，guest observer SHA256 `6331e467d8446e235af0babf1a80bf851b2b5d425f1ea2c7424bb3702f954507`；UPM两笔、all13 accepted、broker、归档读回、detach、唯一ID QMP quit、QEMU rc0、无信号和租约闭合。该轮未发送4147，单独记录未覆盖，不借用首轮收据记本轮通过。

第三轮首个负发送推进到4080/type5/12B，wire `050080404100008000000000`，destination90030001、source80020002、rc−1020，继而原FirmwareFault。原handler0x357bd4写word+0x1fc后调用0x8da97e，后者依赖配置+21c/+214/+2a4/+228/+224/+200/+208/+204/+20c/+210，派生写word+22c/+230/+234和byte+218。它不是仅日志的STORE_BYTE合同，不能只接受主写入却省略辅助函数。完整原字节和指令在 `4080-audit.json`、`cp-008da97e-300.json`、`4080-helper.stdout`，逐分支公式和下一步依赖在 `4080-frontier.md`。本轮按有界同类续推范围停在这一新合同，未添加4080或改变原拒绝；父会话下一消费者需实现带来源的完整派生逻辑及未知值处理。当前生产与正式derive保持已核收4151状态。

相邻40d5/40d6只读审计未加入产品，因为本轮未观察到它们。本轮续推2个参数命令（40d3、4151），没有超过最多3个的范围。

完整核收由 `finalize.py` 的两组两线程分别校验原日志/guest消费者/UPM生命周期与归档完整摘要/源码恢复点。只在自然quit、rc0、无信号、detach和租约到退出均有收据时记资源闭合。EE、自然4038与JPEG尚未通过。

空间门禁为64GiB余量加12GiB新增峰值，已通过；生成前可用字节见 `manifest.json`。最终新增实占、保留原因、下一消费者及实际文件系统可用量由 `storage.json`记录。当前不回收受保护原日志、恢复前像和当前derive；这些材料交父会话核收，不能仅因是scratch即删除。
