# overwrite：原厂脚本实际执行与回退自测

原厂脚本补丁的实际执行与下次启动回退已通过两轮 guest 验收，main 另行核串口、manifest、原件和 SD。原始第一轮失败不改写；不从这个脚本推导任意 ELF/共享库补丁兼容。

## 最终两轮：执行与回退通过

修正后的实验使用同一基础 cpio SHA `4d2b9b01c329df5cf4f99974219d110144a967c8d43c5c7302832d0ce23feecf`，正常 profile 的默认重建策略不变，仅私有实验脚本明确跳过重建：

| run | 覆盖状态 | guest 实际脚本 SHA | 实际执行 |
| --- | --- | --- | --- |
| `run-_seek7pp` | 唯一普通脚本 replace | `f42a90d3ebc1578aefbb30e6473d9bb7a85f051bf0504ee162e1960db1bc38c2` | 返回 7 |
| `run-uyzl7xqy` | 关闭覆盖，原始启动 | `845f5d3c5d6827e9719321d0898e8199aeae4f6979922f1da8b45d0b8c1e0ff8` | 返回 1 |

main 重读两份原始串口证据，确认缺失测试密钥前提、guest openssl 摘要和实际执行返回均匹配；原 script 的宿主摘要保持原值。补丁 manifest 的基础 cpio、唯一旧/新条目正确，回退 run 没有 overlay manifest；两轮结束后的基础 cpio 与排队前 pin 一致。

两次关闭都原 Flush=0、owner 恢复，导出卡均为 `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`。main 独立重算整卡摘要并再次运行 fsck，全部通过。实验总体 `ok=true` 只指这份原厂脚本控制流补丁及回退；capture 和 arbitrary_binary_compatibility 字段保持 false。

交付只读证据复核器 `report/overwrite-execution/verify.py` 不依赖 scratch 工具，在成果根目录执行：

```bash
python3 report/overwrite-execution/verify.py \
  --patched runtime/analysis/menu-runs/run-_seek7pp \
  --rollback runtime/analysis/menu-runs/run-uyzl7xqy \
  --base-cpio runtime/analysis/menu-initramfs.cpio \
  --original-script runtime/analysis/menu-root/usr/bin/get_finger_print.sh
```

已实际执行并返回 `ok=true`。若后续正常 rebuild 改变 cpio，应使用该次实验保留的基础镜像核对，不能删掉原件不变检查。原始固件与 guest 产物不混入公开包。

## 第一轮：执行通过，回退前摘要保护拒绝

实验 `scratch/overwrite-execution/drive.py` 仅派生替换 `usr/bin/get_finger_print.sh`，把失败默认值 `RES="1"` 改为 `RES="7"`。其余脚本不变；原宿主文件不改。执行前检查 `/tmp_network/ssh/ssh_host_ecdsa_key` 不存在，前提返回 0 才继续；不读取或删除实际密钥、不连真实网络。

真实 `run-kqmh_mk8`：

| 核对项 | 实际结果 |
| --- | --- |
| 原脚本 SHA-256 | `845f5d3c5d6827e9719321d0898e8199aeae4f6979922f1da8b45d0b8c1e0ff8` |
| 派生脚本 SHA-256 | `f42a90d3ebc1578aefbb30e6473d9bb7a85f051bf0504ee162e1960db1bc38c2` |
| guest openssl 读回 | 与派生 SHA 完全一致 |
| guest 直接执行脚本 | 实际 `OVERWRITE_EXEC_RC=7`；原 ssh-keygen 失败路径被执行 |
| manifest | 唯一 replace 条目；旧/新 SHA、168 字节、原 mode/uid/gid 均有记录 |
| SD 正常保存 | 原 Flush/恢复成功、fsck 0，main 再读整卡 SHA 与 export 一致 |

这一有限结果写入 run 内 `overwrite-execution.json`，原串口在 `overwrite-execution-serial.txt`。SD 摘要为 `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`。原脚本宿主摘要仍为原值。

外层实验接着在第二轮启动前失败：发现基础 cpio SHA 与排队前 pin 不同，拒绝继续。根因是正常 `profile_environment()` 故意剥除外部 `SKIP_REBUILD`；私有启动器因此执行了 rebuild，实际 overlay manifest 所用基础变为 `de6d0b8961de12b15c1ed78d7281b85c9748341551da3e0c6c7dd1407a9542b0`。不能把“基础被正常重建”误说成 overlay 改坏了原件，也不能关闭摘要保护继续。

首轮外层日志和结果另存 `scratch/overwrite-execution/experiment-dw5mg4q4/first-attempt.log`、`first-attempt-result.json`，总体仍 false。第二轮没有运行，所以没有回退成功证据。

## 修正后的验收入口

私有派生 launcher 现在在其脚本内部明确 `export SKIP_REBUILD=1`，使用已验证基础 cpio，不依赖会被正式 profile 清掉的外部环境。仍保留启动前基础/原脚本 SHA 核对，不改变正式产品 profile 的重建策略。调度改用不持锁等待已有启动器的 `idle_lock`。

`test_launch.py` 核两个派生 launcher 的 Python AST、Bash 语法、原脚本前提和显式 skip 位置，连同调度竞争/异常测试合计 **5 passed**。之后单独执行两轮的成功结果见首节；这里保留修正路径，不将首次失败改为成功。

这项范围是原厂 shell 工具的真实控制流变化，不是“文件里增加未消费标记”。它仍不证明相机拍摄业务、任意二进制布局、固定地址 observer 或 CP 协议兼容；相应字段保持 false。
