# 下一轮菜单设置：语言与日期格式

主会话复用与当前 AP 同 SHA 的现有反编译 corpus，找到原 `lib::backup_get/set_language` 与 `lib::backup_get/set_date_format`，再按 ELF PT_LOAD 映射独立核原指令、PLT/GOT 和 `.rela.plt`。这是静态参数合同，尚未运行这些设置的保存/恢复验收。

| 设置 | Backup ID | 长度 | 原 getter VA | 原 setter VA |
| --- | --- | --- | --- | --- |
| 语言 | `0x02cf0401` | 1 B | `0x35ab650` | `0x35ab690` |
| 日期格式 | `0x02cf0403` | 1 B | `0x35ab43c` | `0x35ab54c` |

getter 传 `w2=1`、构造对应完整 ID，经 PLT `0x165e270` / GOT `0x5bc1940` 的 `Backup_nread` 读入单字节。setter 构造 owner/SID=`0x02cf`、相同 ID 和单字节地址，调用 PLT `0x165eb40` / GOT `0x5bc1da8` 的 `Backup_write`。原符号绑定由 ELF 重定位确认，不只是反编译函数名。

公开 seed 只读解析：bank0 的 SID `0x02cf` 有6873项，起索引30536；这两个属性 `attr=64`、长度1，初始内容分别为 `01` 和 `03`。这些值仅是 seed 字节，不据它们猜具体语言/日期标签；后续用实际原 MENU/LCD 选项和原 API 同步读值映射。超过255的 SID 在原文件存在，不能按锁表低8位索引限制其有效域。

复核：

```bash
python3 report/config-parameter-contract/verify.py --ap runtime/analysis/menu-root/usr/lib/appFw.so
```

main 已执行通过，输出 `static_parameters_verified=true`，菜单改变、保存文件与配置持久化均false。首次复核器的一个 PLT 预期字节抄写有误，校验正确拒绝；main 重新按 PT_LOAD 读原字节、加入两个PLT精确字节并独立解码GOT后复测通过，没有放宽样本身份或业务判断。

下一轮只通过原语言首设/日期格式 UI 修改这两项，原 `Backup_nread` 记录值；在原相机已启动、与已知保存条件一致的阶段调用公开 `Backup_sync_subsystem(0x02cf)`，核完整文件和两个目标字节。随后将已校验文件放入新VM、在启动seed再次写入前用原getter读回，并核原LCD。host store/CAS/生命周期应围住整个保存恢复流程。不能从SID51启动记录成功推导此SID或全部设置都能同步，不直接写这两个字段冒充菜单修改，也不盲遍历其它SID。
