# CP 302c implementation status

当前实现只覆盖 source-derived 的 **no-transition branch**，并保持 default-off。它要求公开 all13 图前置、`MENU_CP_BACKGROUND=virtual-mode3-cold-v1`、精确 `MENU_CP302C_NO_TRANSITION=virtual-cp302c-current0-no-transition-v1`，并在构造时初始化独立虚拟 owner。

已闭合的 source contract：

- 主核显式清零边把 RAM current `0x1a52ad4` 清为0；这个事实只属于 clear return 时点。
- 正常 3007 的 family1/event304 有限边在原 sender 的回复实际 free rc0 后，预测中央局部路径 `0→57→0`。
- 当有效 current0 查询 `3041` 不可接受时，原 outer 可走 `4b4b00→b22788`，产生独立12 B `type1/cmd302c/status=f000` 回复；byte1 源值未知，虚拟 padding 只被明确记录为实现值。它不执行 normal 3041、模块完成、mask 更新或 EE ready。
- 公开 CP 原件的 320 行 current0 表和本轮前缀入口均独立读回，见 `cp302c-prefix-state-preservation-pins.json`。

已落地的 finite owner：

- `device-models/cp302c-no-transition.c/.h`：严格输入、cookie/source、独立 reply、原请求与 reply ownership、sender/free/tid 和 guard 生命周期。
- `device-models/cp-background-device.c/.h`：成功原 3007 reply 的发送返回后、真实 free rc0 后，锁外发布前驱观察回调。
- `menu-observe.c`：最早 CP API entry audit；新 302c dispatch 在旧通用资源路径前；free observer 只接收真实成功释放；全13/OSD persistent references 的内容快照门禁。
- `build-observers.sh`：加入新 backend。

当前明确允许的 type5 接收白名单只有：

```text
source=0x80020002
endpoint=0x90030001
type=5
command=0x402a
bytes=12
```

402a 的原 handler 只写其参数域并绕过 common apply 标记；实现只记录有限历史，未声称原配置消费。4023 的 `8306→3031` 条件路径、公共 apply 的 release 工作、404e 的 0901 consumer 和4139 flag consumer 仍未全部闭合，所以本轮真实前缀中的第一条 `40b8` 会使历史失效，后续 302c 仍拒绝。

验证结果：CP owner/observer/backend/输入审计目标测试通过；全部 profile/constructor 回归 **289 passed**。冻结回归收据为 `scratch/cp302c-noconvert-host-regression.json`：**2314 passed、216 subtests、78 modules、336 C/H/S sources**，测试前后源码哈希稳定。标准 observer 构建完成，原 libc2.25 ABI 自检通过；observer SHA 为 `64f84a9da1032ce70872ef7d89601b6f592579f774e7f5f371b1e178c0f29104`。

唯一 CP302c 诊断 run `run-wsefr5ai` 已实际记录完整302c输入。由于此前真实未知 `40b8` 前缀使 history invalid，原3007回复虽然发送后由原sender free `rc=0`，但没有被owner接受为前驱；随后302c记录为 `UNADMITTED`, `requests_accepted=0`, `faults=1`, 无 reply queued。固件进入 exception monitor，GTK proof 为 `ok=false`；QEMU/GTK/Xvfb随后由精确进程组正常SIGTERM清理，未使用SIGKILL。收据见 `menu-runs/run-wsefr5ai/cp302c-native-refusal-evaluation.json`（SHA-256 `9f1e74d22fe77f59d1a02cbbbca489af9b4d64ae768419eafe4827f19e3b6315`）。这次运行没有产生JPEG/MP4，也没有native302c成功声明。现阶段：

```text
302c_native_verified=false
original_CP_executed=false
normal_3041_transition_supported=false
module_completion_verified=false
EE_ready=false
frames_verified=false
capture_verified=false
JPEG_verified=false
MP4_verified=false
```
