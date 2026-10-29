# 404e type5 输入：0901 consumer 边界

公开 CP 原件身份：18,090,880 B，SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。地址为 CPVA，文件偏移为 CPVA−`0x108000`。

本轮原输入是 **8 B**：`05004e4004000080`。`355538` 不读取消息尾部；因此不能因本轮缺少12 B尾部而缩小真实 fallback 链。

当配置 root `b2ddb4()+34` 指向对象的 byte `+2a2` 为非零时，handler 只递增参数域 `165a720+7a7`。否则执行：

```text
35555e..355582 → 7ec50e
→ 构造 12 B：u16=0901, byte+4=0, u32+8=1
→ 7faad4 → 2ab280 → 564b38
→ endpoint 90060197
```

该消息确实有原消费者，不是可忽略的发送记录：`2ba6b2→7faae0→2ab2d8→5653a8` 接收，`80d25a` 将 type1 消息放入 owner `+48c` 队列，`80d2b6→2ba000(owner,msg,1)` 执行查表。type1 的表为 `d7577c`，72 项、stride20；index 为 `msg[1]=9`，表项 `d75830` 为：

```text
10, 2a0e8d, 0, 1001, 0
```

handler 为 `2a0e8c`，原字符串为 `Camera::FC::FCTop::ExecApiCancelTracking(const void *)`。它受 FC flag `u32[1810588]` 和 owner `+4b4` 等门控，并会向同一 FC endpoint 排入 type0/event `15`、`09`、`0c` 序列消息，调用 FC 序列及虚函数分派。完成 fanout 还可经 `9cbc24→a1647e→3de048→a40ebe→50ff1c→a3f226` 进入识别数据消费者。

这些域均独立于中央 current `u32[1a52ad4]`。目前没有闭合 FC 序列事件、完成 fanout 和识别数据消费者是否会生产中央命令或触发 `b1f238` 的完整因果链。current0 命令表允许多个其它 command，因此不能用“未知命令最终一定会被 current0 拒绝”替代该缺口。

结论：

```text
404e_preserves_current = false
whitelist_404e = false
original_config_consumed = false
302c_native_verified = false
capture_verified = false
```

0901 的实际接收/执行链已进一步闭合到 FC API：

```text
90060197
  → 2ba6b2 → 7faae0 → 2ab2d8 → 5653a8
  → 80d25a：type1 消息进入 owner+48c 队列
  → 80d2b6 → 2ba000(owner,msg,1)
```

`2ba000` 使用72项 type1 表 `d7577c`，`msg[1]=9` 选择表项 `d75830`：`{0x10, 0x2a0e8d, 0, 0x1001, 0}`，实际 handler 为 `2a0e8c`，原字符串为 `Camera::FC::FCTop::ExecApiCancelTracking`。它受 FC flag `u32[1810588]` 和 owner `+4b4` 等门控；满足条件后还会排入 type0/event `15/09/0c`，触发 FC 序列和虚函数分派。

该 handler 还可调用 owner `+2e4` completion callback。回调注册链为 `9cb9ea→7e8530`，随后构造 type1/3301 请求；完成 fanout 经 `9cbc24→a1647e→3de048→a40ebe→50ff1c→a3f226` 进入识别数据处理。FC 序列事件、`80d080` 虚函数回调和 `a3f226` 后续消费者尚未闭合，尚未证明它们不会触达中央 current/START。

因此不能使用 current0 的命令表“不包含某 command”替代这些异步消费者的完整因果证明。404e 仍继续使历史失效。

关键源码窗口（16 个，原件内，940 B）包括 `355538/7ec50e` fallback、`90060197` receive、`d75830/2a0e8c` handler、`2a0eba` guard、`7e8530/7e8758` callback fanout、`9cbc24` completion path；正式实现继续在遇到404e时使历史失效。