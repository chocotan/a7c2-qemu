# 普通读取权限边界的限定验证

本目录是本次新增的 host-only 验证快照，`flavor=null`。授权改动仅三个 codec 实现/测试文件及上级 README；原 header、source pins、main、evidence checker、历史运行和已加载库均未修改。没有运行 VM、GDB/QMP、GUI、网络、完整回归或主 `.so` build。原 SDK 方法/返回PC、输出内存provider、broker/Fsys仍有明确 HOST_TEST 夹具；`capture_verified=false`。

## 已完成结果

| 阶段 | 结果 | 原始记录 |
| --- | --- | --- |
| 父全批首次失败 | 1 failed /4669 passed /5740 subtests；原文件只读，最终再次核对摘要一致 | `prior-failure-reference.json` |
| `/proc/self/mem` 权限探针 | retained `PROT_NONE` VMA，22B `pread` 全部等于已知原值 | `proc-mem-prot-none.json` |
| 新 guard + 旧生产，首次 pytest | rc1；子进程rc-6；错误进入原方法时borrow/release/write/encode/send全0 | `before/pytest.stdout` |
| 新 guard + 旧生产，连续重复 | 400次预期结果；短对象和status0短DMM每模式各50次稳定预失败，合法40B对象和4B失败DMM每模式各50次通过 | `before/summary.json` |
| 修复后完整 codec 矩阵 | 223 passed in 34.24s；110 normal +110 SAN +1 public-source pin +2实际stdout/checker | `after/pytest.stdout` |
| 首次矩阵+重复组合命令 | 工具60秒上限，完整矩阵rc0及384次成功重复保留；不声称该组合命令完整完成 | `after/summary.json`, `after/orchestration-timeout.json` |
| 修复后独立完整重复 | 400/400 rc0；四场景 × 两模式 × 连续50次 | `after-repeats/summary.json` |

每个重复保留序号、rc、stdout/stderr字节数与SHA-256；每场景/模式首份 stderr 原样保留。预失败被断言截停，borrow_count、requests_freed、release_count、serialized_writes、bridge_stills、send_calls全部为0。修复后的短对象/短DMM/不可读首页要求return0x201、errno=EFAULT、原方法调用0、借用0、释放0、写入0、编码0。仅4B失败DMM继续运行原方法并保持return1和输入errno；合法40B对象每次检查真实model/SDK输出、独立解码和原配置长度写回。

新边界测试还覆盖第一页对象/trigger不可读、R对象、RX对象、跨连续RW/R VMAs的40B对象。两页guard映射不留洞，退出统一释放两页；config映射仍只释放一页。生产只有一份共享maps parser，原五个写检查继续要求RW，所有read_object在有界pread前要求普通可读权限，原整数边界、pread/close错误及errno保留。

## 复现

以下命令从 `2026-10-17-qemu-native-camera` 成果根目录运行。依赖使用原Python/C测试已有配置，没有新增包。所有新输出必须留在本scoped目录，已有输出禁止覆盖。

当前源码的完整限定矩阵：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=report/functional-jpeg-codec/verification-readable-guards/recheck-matrix-builds \
  runtime/analysis/test_functional_jpeg_codec.py
```

复查已保存的旧/新生产可执行文件，分别使用新的输出子目录：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  report/functional-jpeg-codec/verification-readable-guards/run-boundaries.py before \
  --reuse-builds report/functional-jpeg-codec/verification-readable-guards/before/pytest-builds/functional-jpeg-codec0 \
  --output report/functional-jpeg-codec/verification-readable-guards/recheck-before

PYTHONDONTWRITEBYTECODE=1 python3 \
  report/functional-jpeg-codec/verification-readable-guards/run-boundaries.py after \
  --reuse-builds report/functional-jpeg-codec/verification-readable-guards/after/pytest-builds/functional-jpeg-codec0 \
  --output report/functional-jpeg-codec/verification-readable-guards/recheck-after
```

`run-boundaries.py`拒绝已存在的输出目录，core dump禁用。ASan/UBSan沿用原测试环境：`detect_leaks=1:abort_on_error=1:quarantine_size_mb=64`、`halt_on_error=1:print_stacktrace=1`。原free-reuse专用quarantine配置没有修改。原完整矩阵fixture还完成strict host语法编译、已安装AArch64编译器的codec单独object编译、两种host可执行文件链接；未build主库。

权限探针可用以下独立命令复现；只读自己新建的匿名映射，无普通指针读取不可读页：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import ctypes, mmap, os
from pathlib import Path
libc = ctypes.CDLL(None, use_errno=True)
libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
page = mmap.PAGESIZE
mapping = mmap.mmap(-1, 2 * page, prot=mmap.PROT_READ | mmap.PROT_WRITE)
address = ctypes.addressof(ctypes.c_char.from_buffer(mapping))
payload = b'guard-permission-proof'
mapping[page:page + len(payload)] = payload
assert libc.mprotect(address + page, page, 0) == 0
try:
    line = next(row for row in Path('/proc/self/maps').read_text().splitlines()
                if int(row.split('-')[0], 16) <= address + page <
                int(row.split()[0].split('-')[1], 16))
    assert line.split()[1].startswith('---'), line
    fd = os.open('/proc/self/mem', os.O_RDONLY | os.O_CLOEXEC)
    try:
        actual = os.pread(fd, len(payload), address + page)
    finally:
        os.close(fd)
    assert actual == payload
    print(line, actual.hex())
finally:
    assert libc.mprotect(address + page, page, mmap.PROT_READ | mmap.PROT_WRITE) == 0
    mapping.close()
PY
```

## 证据链与限制

- E-proc：实际PROT_NONE读回 + 旧生产只有bounded pread的源快照 → F-read（validated）：proc mem不足以证明普通可读性 → P-read：span/overflow → shared maps read permission → bounded pread → 原对象ABI校验。
- E-before：首次rawerror + normal/SAN各50次预失败计数 → F-guard（validated）：保留mapping后稳定暴露权限漏检；未借用或改写输出 → P-guard：两页mapping/guard → 旧read_object → 原方法入口的安全断言。
- E-after：完整223项 +独立400次全通过 → F-fix（validated）：原拒绝在进入原方法前完成，合法R/RX/连续VMA源仍正常 → P-native：原对象 → 真bridge/core/CMOS/encoder → 原ACK/Comp/free0/lease/长度读回夹具。

`before-*`是开始时原文件快照；`*.diff`是相对这些快照的最终差异。首次编译的旧生产可执行文件另含当时刚加入的保留guard和入口断言夹具，不能把`before-test-functional-jpeg-codec.c`误当为该中间夹具源码。新增加的五个permission场景仅在修复后matrix中执行。`final-summary.json`与`artifact-sha256.json`记录最终源码、构建产物和所有原始输出的摘要；父全批日志维持原状态。

VMA读取权限检查不提供映射活期锁；检查到pread之间仍有TOCTOU。原caller必须维持源对象/映射活期，输出仍依赖externally-owned lease。本次没有证明线程隔离、原AArch64 SDK执行、原AP拍照、原writer或虚拟SD成片。父随后负责新的冻结host全批以及live安全后的完整build/VM验收。
