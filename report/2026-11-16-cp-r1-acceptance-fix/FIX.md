# CP 统一验收 R1 集中修复（只实现 + 语法检查）

证据：`scratch/a7c2-capture-p1-runtime-20261115-candidate50/acceptance-1/failure-nodes.txt`、
`scratch/a7c2-capture-p1-runtime-20261115-candidate50/acceptance-1/cp-startup-storage/stdout.log`

本轮按指令只做实现与语法/静态检查，**未独立重跑验收**（pytest 未执行，QEMU/guest/设备未触碰）。

## 1. 82 个 CP 用例 `NameError: name 'model17c_runtime_profile'`

受影响（共 82 个 node，11 个测试文件，全部经共享 helper `menu_probe_setup` 路径）：
`test_cp302c_diagnostic_constructor.py`(9)、`test_cp302c_diagnostic_profile.py`(4)、
`test_cp302c_no_transition_profile.py`(11)、`test_cp_capture_format_constructor.py`(8)、
`test_cp_capture_format_profile.py`(4)、`test_cp_ee_controls_profile.py`(9)、
`test_cp_movie_format_profile.py`(11)、`test_cp_notification_constructor.py`(8)、
`test_cp_notification_profile.py`(4)、`test_cp_owned_state_profile.py`(9)、
`test_cp_startup_controls_profile.py`(5)。

### 根因（test helper，非功能源码）

`runtime/analysis/test_bb_set_mode_profile.py::menu_probe_setup()` 用 AST 从
`qemu-menu-probe.py` 抽取 setup 片段后 `exec`，其“模块级全局”窗口被限定在
`parser` 到 `base` 之间（`tree.body[parser_start:args_index]` +
`tree.body[args_index+1:base_index]`）。R1 新增的
`model17c_runtime_profile = os.environ.get('MENU_MODEL17C_RUNTIME_OBSERVE','')`
位于 `base`（第 238/239 个顶层语句，源码 538 行）之后（源码 799 行），不在窗口内；
而抽取出的 setup 片段（源码 1418–1988，`capture_seed_setup` → `setup_result`）在第
1944 行读它，于是 `<complete-profile-guest-setup>:1944` 抛 NameError。

traceback 一致：`test_bb_set_mode_profile.py:107 → exec(...) → <complete-profile-guest-setup>:1944: NameError`。

### 修复（patch 0001，共享 helper 兼容）

在 `menu_probe_setup()` 里额外把该 module-level 赋值节点接进 `globals_code`：

```python
    # The setup body reads this module-level admission global; keep the real assignment.
    runtime_profile=next(node for node in tree.body if isinstance(node,ast.Assign) and
                         isinstance(node.targets[0],ast.Name) and
                         node.targets[0].id=='model17c_runtime_profile')
    globals_code=ast.Module(body=[...原窗口...]+[runtime_profile],type_ignores=[])
```

为什么这样修是等价且不削弱断言：
- 保留脚本里**真实**的赋值表达式（不复制常量），仍在
  `mock.patch.dict(os.environ,host,clear=True)` 之内执行，因此读到的是测试给的
  host env；当前没有任何 host profile 设置 `MENU_MODEL17C_RUNTIME_OBSERVE`，取值为
  `''`，`if model17c_runtime_profile:` 分支为假，导出集合与既有断言期望完全不变。
- 只增补这一个名字，没有引入 post-`base` 区里依赖 `base`/`out`/`proc` 的语句
  （`out = ...`、`functional_camera = prepare_functional_camera(...)` 等仍不进入窗口）。
- 该 helper 已在工作树内（mtime 2026-11-16 21:42，早于本次会话），本次原样保留并核验，
  未回退、未改写。

### `model17c_launch_index` 是否是下一个未定义点：不是

- 源码 1946 `model17c_launch_index = len(setup)` 位于被抽取的顶层片段内且无条件执行
  （1944 的 `if model17c_runtime_profile:` 只承担 append），1971/1981/1987 的使用点同在
  该片段内，因此只要 `model17c_runtime_profile` 有定义就不会 NameError。
- 静态名字覆盖检查（抽取片段 = 源码 1418–1972 顶层语句）表明，在 profile 为空时可达路径
  上不再有未绑定名；剩余未提供名只落在**不会进入**的分支里：
  `proc`/`out`(1963–1968，`if capture_seed_setup is not None`)、
  `proc`/`out`(1980–1984)、`functional_camera`(1986)（后三者位于
  `if model17c_runtime_profile:` 内）。
- 已知边界（本次不改）：若将来有测试给 `menu_probe_setup` 的 host 设置
  `MENU_MODEL17C_RUNTIME_OBSERVE=virtual-model17c-runtime-ro-v1`，该片段会需要
  `proc`/`out`/`functional_camera`（真实 GDB arming），helper 需要额外裁剪该分支或补桩；
  目前无此用例，故不预先扩面。

## 2. `test_cp_opcode_batch.py::test_source_bound_parameter_ingress` RuntimeError

失败点（stdout.log）：`device-models/test_cp_opcode_batch.c:439`，子用例 `all-opcodes`：

```
FAIL .../test_cp_opcode_batch.c:439 !handled && rc==123
```

### 根因（测试穷举表未登记 R1 新增 opcode）

R1 在 `device-models/cp-background-device.c` 里新增了抢占式 handler
（`int push_mr=size>=4 && body[0]==5 && opcode==0x40df;`，源码 825 行）：
`0x40df` 不再落进 `!push_mr && (…opcode!=0x3007)` 的“观测后原样委派”分支，而是进入
`if (push_mr) { if (size!=16 || source!=0x80020002u) { *result=-1020;return 1; } }`
（源码 844–846）。`all-opcodes` 循环里未知 opcode 用 `unknown={op,12,…}` 构造 12B 报文，
于是 `0x40df` 得到 `handled=1, rc=-1020`，与 439 行的
`CHECK(!handled && rc==123)` 冲突。

静态枚举（`commands[]` 91 项 + `remainder_commands` 中 BACKGROUND 侧非 0x301a 项 +
`0x4023` + `0x40df`，对照 `contracts[]` 91 项 + 测试现有 6 个特殊 opcode）差集只有
`0x40df`：它是唯一“handler 会处理、但穷举断言表未登记”的 opcode。

### 修复（patch 0002）

在 `all-opcodes` 期望表补一条与既有 `-1020` 早退项同形的分支，断言**当前真实语义**
（12B 被拒、请求未被 dispatch 消费，由调用方 free）：

```c
            /* 40df is handled only as the exact 16B push_mr; this 12B wire is refused
             * before any lease/ownership transfer, so the caller still frees it. */
            else if(op==0x40df){CHECK(handled && rc==-1020);CHECK(!release(NATIVE_CP_BACKGROUND_SID,p));}
```

不削弱断言：原有“其余全部 opcode 必须 `!handled && rc==123`”的兜底分支保留不变；
`0x40df` 的 16B 正常接收路径另有专项覆盖
（`device-models/test_cp_push_mr.c`，由 `runtime/analysis/test_cp_background_device.py` 编译执行，
该文件不在本次失败清单内，未改动）；`active` 计数仍由本条 `release` 平衡，
末尾 `CHECK(records==CONTRACT_COUNT && !active)` 语义不变（push_mr 早退不写 config、
不产生 `PARAMETER_ACCEPT` 记录）。

## 3. 验证记录（仅语法/静态，未执行验收）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 语法 | `python3 -m py_compile test_bb_set_mode_profile.py test_cp_opcode_batch.py` | OK（生成的 `__pycache__` 已删除） |
| C 语法 | `cc -std=c11 -Wall -Wextra -Werror -pedantic -g -DNDEBUG -fsanitize=address,undefined -fno-omit-frame-pointer -no-pie -pthread -fsyntax-only cp-sync-resources.c cp-cold-control.c cp-background-device.c test_cp_opcode_batch.c` | OK |
| patch 0001 与工作树一致 | `git apply -R --check patch/0001-…patch` | OK |
| patch 0002 与工作树一致 | 由“删除新增 3 行”重建 before 后 `diff -u` 生成，行内容逐字核对 | OK |
| 抽取片段名字覆盖（静态） | AST：`glob_body` 现绑定 `model17c_runtime_profile`（源码 799），片段 1418–1972 可达路径无其它未绑定名 | OK |
| opcode 差集（静态） | `commands[]`/`remainder`/`0x4023`/`0x40df` 对照 `contracts[]`+测试特殊项 | 差集仅 `0x40df` |

未做：pytest 执行、C 单测二进制运行、QEMU/guest 运行（按本轮“只语法检查”要求）。
C 测试的运行时行为仍需在统一验收中回归确认。

## 4. 本次实际修改清单

| 文件 | 变更 | 行 |
| --- | --- | --- |
| `runtime/analysis/test_bb_set_mode_profile.py` | `menu_probe_setup()` 增补 `model17c_runtime_profile` 模块级赋值节点到 `globals_code`（工作树内已存在，本次保留并核验） | 52–57 |
| `runtime/analysis/device-models/test_cp_opcode_batch.c` | `all-opcodes` 期望表新增 `0x40df`（12B 拒绝）分支 + 2 行注释 | 439–441（新增 3 行） |

patch：`patch/0001-menu-probe-setup-keep-model17c-runtime-profile.patch`、
`patch/0002-test-cp-opcode-batch-exhaustive-40df-refusal.patch`。

未修改（按指令不越界）：

- `runtime/analysis/test_functional_camera_runner.py`（12× `StopIteration`、
  1× `NameError: guard_live_owner`）——runner lifecycle 文件，禁止改动。
- `runtime/analysis/test_qmp_strict.py`（48× `AssertionError: Private test group required`）——qmp strict 文件，禁止改动。
- `runtime/analysis/test_model17c_gdb_owner.py`（`FileNotFoundError`：原始 asset 缺失）——资产依赖问题，非 test helper/源码兼容问题，本轮未处理，留给对应专题。

## 主会话复验更正

acceptance-2/3/4 与主会话限定诊断最终确认：`all-opcodes` 的 40df 样本是 type5/12B，但该夹具没有 allocate/send/set_source，故在原尺寸检查之前以 `missing-transport` 返回 `-1021`，请求仍由调用方释放。最终穷举表登记这一真实行为；type5/16B 正常与错误路径继续由 `test_cp_push_mr.c` 覆盖。原失败与复验收据均保留，未回填旧结果。
