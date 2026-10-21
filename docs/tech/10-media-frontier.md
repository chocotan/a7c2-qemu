# 启动流程 10 · 媒体状态与容量：REC 提示链反查（未闭合）

进入拍摄页面后按 REC，原固件会弹媒体提示。本篇记录这条链怎么逐层反查：
从 LCD 一句话 → 最终选择规则 → 属性读数分层 → 容量对照实验。
**"无空间"的完整根因还没找到，照片/录像没有恢复。**

变量见[索引](README.md)。数值来自历史报告，本次只读源码，未重跑实验。

## 1. 从提示反查"原固件选了哪条规则"

LCD 的一句话不能反推物理槽或容量。做法（`media_predicate_watch.py`）：
用硬件断点把原选择器的 entry/return 配成同一调用，读出所选记录——
规则表 VA `0x58f03a8`、步长 `0xa0`，记录里 `+0x10` 是 predicate、
`+0x38/+0x48` 是主/备 message list。

修掉遗留强写之后，原运行多次选中同一条：

| 项 | 值 |
| --- | --- |
| selector 索引 | `0x223` |
| record VA | `0x5905988` |
| predicate | `0x187f130` |
| 主消息 | `0x0200a1b4`（"存储卡无空间。\n插槽1"） |
| 备用消息 | `0x0200a04a`（"存储卡无空间。"） |

这一步证明的只是"选了哪类提示"——该谓词本身不做空间算术，
上游条件要继续追。宿主提交 REC 的时刻也不是原固件消费按键的时刻。

踩过的坑：旧运行里 still 媒体选择字段（`appFw+0x7e6e7f0`）从 0 变 1，
曾被当原固件默认；实际是模拟器自己的遗留 `KEY_GATE_OVERRIDE` 写的。
移除全部七项业务裸写后，REC 提示从"插槽2无卡"变成"存储卡无空间"——
这证明错误首写被纠正，**不**代表媒体链恢复。
（详见 [12-debugging](12-debugging.md) 第 6 节。）

## 2. 属性读数分两层：基值和值层

规则依赖的读数要先分清来自哪一层。属性分发表 `0x5584c38`、行步长
`0x30`：原 API `0x28bb0ac` 走行 `+0x08`（基值/复位源），
`0x28bb0c8` 走 `+0x20`（值层）；`+0x10/+0x18` 是 setter。
三层不能合成一个单元。例如 `0x102d` 的基值 cell 是 `0x7e83b28`、
值层是 `0x7e83b10`；`0x102e` 对应 `0x7e83b48` / `0x7e83b30`——
两层是不同地址。

踩过的坑：旧日志把 `+08` 的读数（102d/e = 0/30）叫"实时值"，
由此断言"整个启动从未更新"或"0 = 未挂载"。两个解释都撤回；
现在两层分别采样、用中性键名（`dispatch_<key>_base08/value20`）。

## 3. 名字目录编号 ≠ 分发表键

名字目录 `0x57f99a0` 的名字只是查找线索，不是已证绑定。
实际反例：目录里 `0x1052` 叫"建新文件夹剩余容量"，但分发表同号键的
setter 受 `(-15,15,1)` 范围校验，实际转接自 `0x103c`，
原字符串是 `set_picture_profile_black_level`——这是 PP 黑电平，
不是媒体容量。原"剩余容量为 0"的说法已撤回。

**这条限制适用于所有仅由目录派生的媒体标签。**

## 4. 校验器和序列化导入不是实时生产者

沿属性 ID 追到的函数要先核用途：`0x2e2232c` 读 snapshot 字段传给
`0x28bbcc8`，后者经 `0x56c4118` 的 24B 记录取函数指针做范围/枚举校验，
返回值表示合法性，不是状态发布。
已核的 `0x02cf0f05/0x02cf0b91` 是设置序列化键，不能改称 CP 消息 ID；
mode 导入缓冲的实际 stride 是 `0x2074`。
按偏移扫到 store 只是候选，不证明唯一写入者。
真实 setter 调用栈和媒体消息 writer 仍需实际观察。

## 5. 容量对照：先让镜像合法

想用更大的卡做对照，先确认实验没在输入阶段失败。后端契约
（`rm-file-device.c`）：`55 aa` 签名、512B 扇区、
**BPB 总扇区精确等于文件长度/512**、每簇扇区数为 2 的幂。

踩过的坑：首轮 1 GiB FAT16 有 2097152 扇区，但 mkfs 默认几何让 BPB
只声明 2097144——fsck 返回 0 也不满足后端全长契约。这是构造问题，
没进入原 REC，不能记作"大卡被业务拒绝"。修正几何为 64 heads/32 sectors
后重新构造，失败输入保留不覆盖。

```bash
# 执行目录：自己的独立实验目录；IMG 为已构造、已关闭的普通镜像；只读检查
fsck.fat -n "$IMG"
python3 - "$IMG" <<'PY'
import os, struct, sys
with open(sys.argv[1], 'rb') as f:
    b = f.read(512)
    size = os.fstat(f.fileno()).st_size
bps = struct.unpack_from('<H', b, 11)[0]
total = struct.unpack_from('<H', b, 19)[0] or struct.unpack_from('<I', b, 32)[0]
print('file_bytes=', size, 'bytes_per_sector=', bps, 'total_sectors=', total)
print('bpb_bytes=', bps * total, 'sectors_per_cluster=', b[13])
PY
```

## 6. guest 交付资源：RAM 是真约束

第二轮失败在更前面：1 GiB 输入加原 cpio，解包到约 1587381 KiB 时 OOM，
连 shell 都没到。DTB 给内核的 RAM 是 `0x140000000`（5 GiB），
Sony 预留后实际可用约 1190024 KiB；QEMU `-m 24576` 不等于内核能用 24 GiB。

后续只对**已证空白零尾**的输入用 metadata+零洞表示：guest 重建后
整卡 SHA 必须等于完整源输入，才允许进原 bootin。这没扩大 RAM，
任意非零尾大卡不适用。

## 7. 工具也要自证

零尾重建曾被 BusyBox 阻断：原 `dd` 不支持 `conv=notrunc`，
`set -e` 下提前退出，bootin 被 SHA 门挡住。console 里 App/Frame/RM
计数全 0——应用没启动，不能解释为"容量条件无效"。
工具行为要用同一原 BusyBox 二进制实测，不能查 GNU dd 手册推断。

## 8. 有效案例的结论边界

最终有效 1 GiB 案例（`run-lptxo5re`）：启动前 guest 整卡 SHA 与输入一致，
原 RM 接受 1073741824B，原 Fsys 报告 65518 总簇中空闲 64917
（约 1014.33 MiB，16 KiB 簇），独立 fsck=0。**原 LCD 仍显示
"存储卡无空间。"**，64 对 selector 中 62 次选 `0x223`。

结论只能是：这组更大、合法的 FAT16 输入不足以解除拒绝。
交付表示和簇大小与 128 MiB 参照不同，不是严格单因素因果；
不能推出"容量全部无关"。

## 9. 当前状态

已建立：最终规则、读数分层、一个有效大卡案例；已撤回：
"挂载/剩余状态必为零"、"唯一根因是逻辑槽"等旧解释。
未闭合：真实 setter 调用栈、shadow→current 提交、媒体消息 writer。
没有通过写 remaining/recordable/ready、选槽或清错来消提示；
`capture_verified` 仍为 `false`。

## 证据入口

- [规则、PT_LOAD 与历次更正](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/capacity-recordable-frontier.md)
- [访问器纠正、1052 反证、合法输入/OOM/dd 及最终案例](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/media-producer-frontier/README.md)
- [首写来源与七项强写删除](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/media-firstwrite-root-cause.md)
- [本包只读诊断修订及发布局限](../../validation/README.md)

## 如果你在做别的机型

属性表、名字目录、规则索引都要重新定角色，同号不能强绑。
顺序：先确定最终原规则，再核地址映射和分层访问器，再找真实 writer；
输入合法、guest 收到相同字节之后，才讨论业务是否接受。
一次改一个变量；有混杂因素就收窄结论，不要补根因故事。
