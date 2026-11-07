# 完整系统、持久盘与开发更新源码

这里发布当前 `a7c2-re` 工作树中的完整系统路线，和仓库根目录原有的 ALLLANG 原生菜单路线分开。源码包括原启动阶段账本、持久虚拟内部盘、同实例恢复、低延迟显示/输入、固件开发 UI、虚拟 USB 控制、P1 U/D/E 构建与 DEV 身份适配、默认关闭的受限 CBC 模型及对应测试。此次为源码移交；本包没有重新运行 QEMU、构建 guest 库、接入宿主 USB 或验证安装。

最新已闭合研究结果见[11月7日进展](../../docs/tech/2026-11-07-current-progress.md)和 [v35 收据](../2026-11-06-system-update-runtime/p1-dev-identity-v35-actual.json)。v35 两个原 Initialize 返回0，后继原 receiver 因 `verifySum` 的 39447≠60944 返回1。安装、完整 BODYDATA 读完、原 writer、完整启动、USB认证和成片保持未验证。40a5 仍禁用。

## 路线与外部输入

| 入口 | 用途 | 必须自行准备的输入 |
| --- | --- | --- |
| `boot-session.py` / `boot-execution.py` | 独立原冷启动、阶段绑定与拒绝不完整启动 | 只读完整 dump 或已准备的独立 runtime、原 kernel/DTB/库、明确的虚拟卡 |
| `persistent-boot.py` / `camera-disk.py` | 原分区布局、同实例持久盘、租约和启动资产绑定 | 用户自己的明文镜像；通过 `factory-images.py` 生成普通虚拟文件 |
| `retained-camera-launch.py` / `newretained-camera-execution.py` | 同盘 RAM 恢复、QMP/进程/lease 和资源身份核验 | 按源码构建的精确 QEMU 组合及新鲜来源收据；原 RAM/盘不是源码资产 |
| `firmware-development.py` / `run-retained-camera.py` | 开发工作流与 UI 接线 | 以上独立实例、原资产和实际构建的 `camera-ui-rs` 程序 |
| `update-boot.py` / `p1-dev-install.py` / `p1-update-execution.py` | 显式本机虚拟更新 U/D/E、完整来源/归档读回 | 自有官方 BODYDATA、原 .186 更新环境、原 SDK 库、原资源模块及显式授权文件 |
| `p1-dev-receiver-identity.py` | 对已知四字节派生 receiver 生成隔离 DEV file-media C | 精确 stock/derived receiver、逆证明、未变 Initialize 窗口、真实编译器和原 libc |
| `usb_control.py` / `usb-device-profile.py` / `usb-gadget/` | 虚拟设备、VHCI owner/namespace/port 与源身份守卫 | 显式虚拟 USB profile、构建产物和实际本机 VHCI；host tests 只使用合成 sysfs/socket |

仓库不提供 Sony 固件、完整 dump、rootfs、BODYDATA、Backup/settings、Sony 密钥、原运行日志/图片、CPIO、ELF/DSO、虚拟卡或内存。`runtime/native-input.json` 及完整私有 native snapshot 也不随附，**不会用空状态或旧二进制冒充这些输入**。缺少或摘要不匹配时原校验继续拒绝。

完整 fwtool 依赖由读者显式提供，项目地址为 <https://github.com/ma1co/fwtool.py>。根目录 ALLLANG 路线随附的 fwtool 只是其已许可的 FAT/解包子集，不等于完整 `sony`/`ext2` 模块。DEV package API 的 `fwtool_dir` 参数须指向读者准备的完整源码；Python 需要本仓库 `requirements.txt` 中的依赖。DEV builder 使用的纯 Python `analysis/build_sony_info.py` 已随本包提供，并记录了公开导出前后的摘要。

`keys/sony-update-public.pem`、`p1_cbc_known_k8.inc` 是受原精确摘要校验的外部输入，本包排除密钥内容。CBC 保持显式、默认关闭且拒绝继承到 DEV；没有这些输入时不能构建 CBC provider。`usb_jiritsu.py` 的可选消费者还需要显式 `A7C2_VIRTUAL_JIRITSU_SCRIPTS` 和 PMCA 依赖，涉及真机部署的历史脚本与载荷不在本包内。缺少这些输入将得到 blocked；测试会明确跳过该独立外部阶段，不能声称认证/root 通过。

## 准备独立 native 依赖快照

先按仓库根 README 从自有官方包准备资产并构建原生路线。然后在本仓库根明确选择输入，而不是读取其它工作区：

```bash
python3 report/2026-10-17-qemu-full-system/native-input.py \
  --capture-from "$PWD" --select
```

这个命令要求 `EXTRA` 中列出的原生构建产物和固定 QEMU 归档均已存在，复制到被忽略的完整系统 runtime，并逐文件绑定摘要/权限；缺少输入即拒绝，不自动刷新已有快照。完成完整原资产准备后，各启动/更新入口的 `--help` 与函数签名列出其明确输入。此发布没有执行该准备，也没有授予物理设备操作权限。

## 公开 host 检查

在仓库根执行：

```bash
python3 tools/test-system-runtime.py
python3 tools/test-public-models.py
python3 tools/test-host.py
```

`tools/system-runtime-tests.json` 固定选择合成 host 测试；原资产、编译 guest、完整 U/E producer 和 actual API 是独立可选阶段。runner 审计钩子拒绝 QEMU、bubblewrap 和原启动入口，输出标记 `HOST_SYSTEM_RUNTIME_ONLY`。测试数、跳过理由、源码身份与初始失败见[本次源码发布收据](../../validation/2026-11-07-source-publication.json)。源码可用性、host 结果和原研究 guest 消费分别记账。
