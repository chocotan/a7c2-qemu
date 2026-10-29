# 4139 type5 输入：复制参数到 readiness 的边界

公开 CP 原件为18,090,880 B，SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`；地址是 CPVA，文件偏移为 CPVA−`0x108000`。

本轮 `run-r5a1i38g` 的 sequence 34 是 destination `90030001`、source `80020002`、184 B 的完整入口记录。raw 正文完整，接收记录仍标记 `delegated=1`, `consumed=0`, `state_verified=0`；这证明 API 输入，不证明原 CP 消费。

源码链已闭合到 readiness 数据：

```text
record 10fbe74 / handler 8dacea
  → copy message+8, 0xb0 bytes, to P+870
  → byte[P+86f] = 1
  → later 8dad54 publishes a d64-byte snapshot
  → 39f18c reads snapshot+86f
  → nonzero: 9facb4(snapshot+870), then 9fa478()
  → four 44-byte banks cached at 1abbf16
  → 9facfc selects a bank; 9fad10 selects threshold fields
  → 9d9e24 and 9db6fa perform coordinate/status comparisons
```

`9facb4` 具有 cache-valid gate，重复4139不能默认覆盖第一次缓存。银行选择表为 `06 09 03 03 0c`，selector分别选 bank offsets `+58,+2c,+0,+84`；每个 bank 有22个 little-endian u16。阈值字段按selector和argument选择不同偏移。

已确认的 downstream effects 包括：

- `9d9e24` 比较两个坐标差，失败写 reason `0x12` 到 `1b16403`；
- `9db6fa` 比较另一组阈值，失败写 reason `0x0f`；
- 这些结果被 `9d9b12`、`9db6bc`、`9da042` 和 `3c3f78` 继续传播。

中央 completion writer 已定位：`4dacf0→b1f1cc`，要求 `1b1df9d==1`、管理器 ready、boundary test 等条件，最终在 `b1f238` 写 `current=word[1a52ae4]`。后续[NEXT源合同](cp-central-next-state/README.md)已将准备callback `4d7484→4b29e0` 的 `4b2a62` 赋值与commit callback `4d9ebc` 区分，并核原skip分支可phase=1却不赋NEXT。当前没有证据证明4139的 readiness 结果在所有允许的硬件/status未知情况下到达这些操作，也没有证明一定不会到达。

结论：

```text
whitelist_4139 = false
4139_preserves_current = unknown
original_config_consumed = false
302c_native_verified = false
capture_verified = false
```

因此不能用本轮观察到的坐标或把这一 run 的184 B payload硬编码为“有效配置”。继续遇到4139时，finite owner 使 history invalid；这保留了源证据边界和失败证据。独立重复审计 `run-ta52l9mu` 也记录同一完整184 B入口；本轮 payload SHA-256 为 `f873fa32260cd88d4a13e6907078d9a51ff378902eb491af5df072923835c3cb`。请求记录仍为 `consumed=0/state_verified=0`，所以这只是 AP send/input 证据。

关键细节：`9facb4` 的 cache-valid byte 会阻止重复4139自动替换首个缓存；四个44 B bank由 `9fac80/9fab66` 解码，selector表为 `06 09 03 03 0c`。`9d9e24`/`9db6fa` 的 readiness 返回值会进入多级 callers，但与 `b1f1cc→b1f238` current commit 的因果链仍未闭合。不能把已有坐标或本轮payload硬编码成完整配置，也不能把同步 handler 前的 callback chain当作4139 completion。

调查窗口共16个、约1,350 B，包含4139记录、复制/发布、flag消费者、银行解码、阈值比较和中央commit入口：

```text
010fbe74/14  8dacea/38  8dad54/38  4d7a64/62
4d9684/20    39f18a/20  9facb4/58  9fab4a/28
9fab66/282   9fac80/52  3ca620/70  9fad10/142
9d9e86/154   9db7ae/142 4dace8/16  b1f1cc/208
```

这些窗口均为公开 CP 原件 CPVA，raw=CPVA−`0x108000`；RAM/MMIO地址不作文件切片。