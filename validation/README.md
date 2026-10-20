# 本包验证记录

本记录只覆盖独立源码打包、主机检查与官方包准备。**未编译/安装 QEMU 或 guest 助手，未启动任何 VM，未连接真机、物理 SD/磁盘/TTY。** 旧路线的 VM 结果只作为 README 中标注的基线状态，不冒充本包验收。

## 实际检查与结果

| 证据（本地日志，默认忽略） | 实际结果 | 结论与边界 |
| --- | --- | --- |
| `host-imports.log` | `HOST_IMPORTS_PASS`、`HOST_DEPENDENCIES_FOUND` | 导入器、GTK/UI、控制器、USB/SD Python 依赖可导入；使用被忽略的本地 crypto 前置依赖，未重新安装模块 |
| `source-check.log` | `OFFLINE_SOURCE_AND_BOTH_PATCH_IDENTITIES_PASS` | 核对完整 QEMU 归档 SHA、DTC 全树、native 和 USB 两阶段补丁及 before/after 身份；只提取被修改文本，无编译或 QEMU 执行 |
| `start-help.log`、`build-help.log` | 返回 0 | 入口帮助可用，未触发导入/构建/VM |
| `static-checks.log` | Python AST、Bash 语法、本地 C include 闭合通过 | 静态检查支持以 analysis 为 include 根的 device-models；不能替代 C 编译 |
| `host-tests.log` | **213 passed、31 skipped、71 subtests passed** | 新目录主机测试，包含新增 `/var/tmp` alias 与无关文件保留测试；跳过显示/真实运行证据/构建依赖检查 |
| `prepare-only.log` | 安装 1291 项资产，字体校验通过，`BODYDATA_PREPARED` | 只读现有官方 2.01 ALLLANG 输入；所有派生产物只写新目录被忽略区域 |
| `relocated-prepare-only.log` | `CACHE_VERIFIED`、输入/字体/runtime 校验通过、`BODYDATA_PREPARED` | bwrap 将新包绑定到 `/mnt/package`，把整个原项目路径隐藏；输入单独只读绑定。准备代码无旧路径依赖 |
| `relocated-source-only-tests.log` | **209 passed、35 skipped、71 subtests passed** | 同样隐藏原项目，并额外隐藏 menu-root/unpacked/bodydata-cache；虚拟临时区隔离。验证无 Sony 资产/构建产物也可跑限定 host suite |

导入的官方输入 SHA-256 为 `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`；未把输入本身复制到源码清单。成功缓存和 native-assets 清单由导入器保留在本包被忽略区域。本轮再次核对所选原文件 SHA，原来源文件没有变化。

三个集成用例在 `tools/test-host.py` 中明确标注超出 asset-free/build-free 范围：USB 派生 DTB 的两个测试需要本地 libfdt/DTB，capture gate 原 getter 绑定测试需要原 appFw 字节（及 capstone）。它们的原测试仍保留，可由 main 在构建/准备后执行。完整测试目录中的其它 C、guest 与 GUI 测试也未在本轮执行。

## 失败记录与修正

`host-tests-initial.log` 保留首次 3 failed：libfdt/DTB 尚未构建，且测试与导入并行时原 appFw 尚不存在。修正限定 host suite 的测试范围后，相关集成检查显式 skip，不把未构建步骤写成通过。

`relocated-prepare-initial.log` 保留第一次隔离布局因只读根无法创建 `/input` 的失败；改用现有 `/mnt` 下的私有 tmpfs 后成功。

`relocated-tests-initial.log` 保留两项 USB 短别名测试在只读 `/tmp` 下失败；本包把别名迁到 `/var/tmp` 并添加“不删除无关文件”的检查。隔离复测为 `/var/tmp` 提供私有临时区，没有放宽原项目路径或资产隐藏。

fwtool SDK 在 Python 3.14 上会发出其已有正则字符串 `SyntaxWarning`，不影响本轮 prepare 成功；本包未顺手改第三方解析器。

## 复现与 main 待验证步骤

在本包根执行：

```bash
./tools/check-host.sh
python3 tools/check-source.py
python3 tools/test-host.py
./start.sh --bodydata /path/to/BODYDATA.DAT --prepare-only
sha256sum --check SOURCE-SHA256SUMS
```

重定位准备测试使用以下隔离布局；`bodydata` 换成自己的普通官方文件：

```bash
package="$PWD"
bodydata=/path/to/BODYDATA.DAT
mkdir -p runtime/tmp
bwrap --unshare-net --die-with-parent --clearenv \
  --ro-bind / / --dev /dev --proc /proc --tmpfs /mnt --dir /mnt/input \
  --ro-bind "$bodydata" /mnt/input/BODYDATA.DAT \
  --bind "$package" /mnt/package --tmpfs "$package" --chdir /mnt/package \
  --setenv PATH /usr/bin:/bin --setenv TMPDIR /mnt/package/runtime/tmp \
  --setenv PYTHONDONTWRITEBYTECODE 1 \
  python3 /mnt/package/runtime/analysis/bodydata-launch.py \
    --bodydata /mnt/input/BODYDATA.DAT --prepare-only
```

main 仍须串行执行 `./build-qemu.sh`（含 QEMU 冒烟测试），再实际启动本包入口，复验单 GTK 窗/LCD、中文首设与 HUD/MENU、输入、USB 初始 OFF 与 ON/OFF/ON、SD 保存正常退出和跨运行回载。本包 helper 构建、cpio 启动以及 `/var/tmp` 短别名的真实 VM 消费均待验证；照片/录像、AF/CMOS/编码、宿主声音、配置跨 VM、SD 动态热拔插和真实无线关联继续标为未完成。

以上为首次打包验证时的记录，当时尚未提交或推送。后续已在本目录独立 Git 仓库进行发布准备；未修改原交付树、父目录 Git 或项目 AGENTS。源码与验证记录按目录分离，验证日志默认不随源码发布。本包仍未编译、未启动 VM，本机动态验证待 main。

## Git 发布准备补充

按用户最终要求，QEMU 完整归档由使用者自行下载；Git 只提供 [下载链接/固定 SHA](../source/vendor/README.md)，不提交大归档或分卷。`SOURCE-ORIGINS.json::external_inputs` 保留本地归档身份，`SOURCE-SHA256SUMS` 更新为实际 Git 源码清单。项目模型、完整 DTC、两阶段补丁和许可证均纳入 Git；没有隐式下载或 LFS 依赖。

发布前复跑受限 host suite，结果写入被忽略的 `publish-host-tests.log`；固定本地归档和双阶段补丁由 `tools/check-source.py` 再核验。官方直链 HEAD 得到 HTTP 200、content-length 141815216（`qemu-download-head.log`），未重新下载归档、执行构建或启动 VM。
