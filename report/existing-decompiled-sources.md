# 已有反编译成果：当前可复用的部分

用户指出的语料确实存在，当前应优先复用 `analysis/appfw-decompile/corpus/`。
独立调查核对 `analysis/evidence/appFw.so` 与当前官方运行树原件均为99960744B，SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
main已实际打开下列正文，与前面独立原字节核验互相印证。

## 直接可用的位置（相对研究项目根）

| 目标ELF VA | 现有文件及正文行号 | 当前用途 |
|---|---|---|
| 339d44c | `analysis/appfw-decompile/corpus/parts/7/0x003390000.c:9506` | enter_rec_still_mode_proc，完整入口流程 |
| 338e924 | `.../parts/7/0x003380000.c:13548` | 第一组callback A，409d/4072/3003调用路径 |
| 338d8f4 | `.../parts/7/0x003380000.c:12868` | 两个token数组的await包装 |
| 303d400 | `.../parts/16/0x003030000.c:2529` | 队列取token、特殊0x2000取消、计数归零 |
| 3531118 | `.../parts/7/0x003530000.c:901` | ushort键到上下文的哈希表插入 |
| 3531300 | `.../parts/7/0x003530000.c:1029` | future检查及等待下游 |
| 354912c | `.../parts/7/0x003540000.c:7016` | key1016的promise/future登记与等待 |
| 35314fc | `.../parts/7/0x003530000.c:1205` | imaging通知入口；2618附近有1016处理及promise完成候选 |
| 34f2f84 | `.../parts/7/0x0034f0000.c:3134` | 原音频032b构造器 |
| 34e521c | `.../parts/7/0x0034e0000.c:5693` | send_no_wait_with_main_thread_i |

表内省略号均指 `analysis/appfw-decompile/corpus`，并不是另一目录。
行号只作定位便利，实际以 `// addr=...` 和 ELF VA 为准。

main已用原查询工具继续追到 `303cb68`（无future时抛future_error）、
`31018f0`（共享状态检查和futex等待），并读到35314fc的1016分支：它按消息键查相同的
promise map，复制消息并调用后续完成函数。尚需对分派原字节和动态命中补核，
不能只靠伪代码据此注入1016或宣称等待已解除。

## 可靠的查询方式与地址陷阱

```sh
python3 analysis/appfw-decompile/corpus.py func 0x303d400
python3 analysis/appfw-decompile/corpus.py func 0x354912c
```

`corpus/manifest.txt` 记录 Ghidra image-base delta=0x100000。
索引和 `// addr` 已归一为ELF VA；`FUN_...` / `DAT_...` 名字通常仍保留加偏移后的地址。
例如 `FUN_0313d400` 对应 ELF VA303d400；不能把名字中的313d400直接当目标地址。
原ELF第二PT_LOAD另有VA=fileoff+10000，不能把两种偏移混同。

反编译器会漏函数参数，例如303d674的声明只显示一个参数，但调用处传入token数组和数量。
非连续函数体、反编译失败、未知类型、间接调用或原子操作都需用原字节补核；
`interior` 查找用entry+size近似，不能把所有内部地址命中都当可靠函数边界。

## 其它资产及尚未确认的覆盖

- `analysis/appfw-decompile/derived/` 与 `analysis/appfw-symbols/`：签名、源文件名、类和虚表辅助；
  推导名字与原厂符号须区分。
- `analysis/appfw-kuna-fill/`：补洞结果，但存在jump-as-call标注，不能当完整CFG。
- `analysis/libobj-decompile/corpus/`：libObj语料，不能套用appFw地址。
- 已有阅读手册位于最终仓库 `report/2026-10-18-appfw-decompile/`，其中
  `manual/01-binary-and-toolchain.md`、`manual/05-model-sequence.md` 适合先读。
- 这次尚未发现并验证完整CP伪代码库，也未确认backup.ko/libbackup.so有可直接使用的原函数C正文。

语料不是可编译的原厂工程。旧统计中1,050分片、318,598索引记录和所谓98.67%不能直接
理解为成功反编译率；重复索引、超时和非连续函数体会影响统计。
本次结果支持立即复用AP流程及等待机制，不代表成像、音频或持久化已经恢复。
