# `000300a8` setup mode 与中央 current 的边界

公开 CP 原件：18,090,880 B，SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。CPVA 文件偏移为 `CPVA-0x108000`；RAM 地址不作文件偏移。公开 ALLLANG seed（SHA-256 `3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`）的 `000300a8` 已由既有 whole-image/BK4 验证器读回：长度4、payload `06000000`，seed 文件偏移 `0x11ece4`；AP bank 缺少该键。该 seed 偏移不属于 CP app image 的文件映射地址，不能用 CPVA−`0x108000` 规则解释。

## 实际 setup 路径

这是 CamMain 的直接调用：

```text
b21598 → b1fd1c
b1fd28: aggregate+108 = CamMain 1a52c40
b1fd2c: r0 = CamMain
         call 4b6744
4b6744: destination = self+30 = RAM 1a52c70
         key = 000300a8, size=4, context=init
         tail-call 510728
```

`b21604` 构造 actor 时清除自己的 `+30`；setup 随后把配置读入 `CamMain+30`。两者都没有写中央 current `1a52ad4`。RTTI 为 `Camera::Function::CamMain`；不能把邻近 vtable 的 `+34` 调用当作 setup 路径。

## `+30` 是 policy input

在已闭合的 `CamMain` 方法范围内，直接引用 `+30` 的位置只有构造清零以及两个 policy reader：

- `b21904(self, flag)`：字段为3时返回0，字段为6时返回传入 flag，其它值返回1；这是 policy predicate，不是 current getter。
- `b218d4(self, opaque, flag)`：按同一 predicate 条件调用 `b0dee6(opaque)`，随后无条件尝试 `b21702(self, 3010, 0)`。

实际 callers 会把 flag 归一化为 `value==1`。相关路径还会触发既有的 disable-BB、CaptureManager bookkeeping 和 family0 event3/6。`b0dee6` 只保存 CaptureManager 的 opaque/pending bookkeeping，没有把 `300a8` 值写入中央 current。

CamMain `+28`、wrapper 的 `+28` 和旧 `cp_cold_create(3)` 参数属于不同字段域。family0 event0/2 会写 CamMain `+28` 为8/2；event4（3007）不进入这些赋值分支。不能从这些数值或旧 mode3 模型推导中央 state6/8。

## current0 不接受 3010

已核对原 320 项中央命令表中的 `3010` 记录：

| record | current | command |
|---|---:|---:|
| `d976a8` | 2 | 3010 |
| `d977c8` | 8 | 3010 |
| `d98358` | 0x6e | 3010 |

没有 `(current0, 3010)` 记录。因此 `300a8=6 → CamMain policy → 3010` 不能从已知 clear-time current0 bootstrap 中央 state6。它也不能证明初始 descriptor 或 current=6。

setup 后第一个未闭合 continuation 是 `b1fd52→b2088c`，其后还有 `b201be`、`b20402`、`b1ffae`、`b20940` 和 `4b3e50`。这些 callees 的异步影响、wrapper flag producer、CaptureManager pending 消费和 successful `300a8` runtime binding 仍未知。

## 实现边界

当前只允许把 `300a8` 表示为独立的 `CamMain.setup_key_300a8` policy input，且必须以实际成功的4-byte readback为前提。不得：

- 调用 `set_current(6)`；
- 把 payload `06000000` 映射为中央 state6；
- 从 `cp_cold` mode3、BB、ADF 或图连接结果借用该状态；
- 把 CaptureManager bookkeeping 当作中央 commit；
- 把 setup 执行本身当作 startup transition。

```text
central_current_from_300a8=false
initial_state6_from_300a8=false
302c_native_verified=false
capture_verified=false
```

证据窗口见 [cp-central-setup-mode-pins.json](cp-central-setup-mode-pins.json)。本调查未运行 VM、socket、网络、相机或 private/full-system 路线。