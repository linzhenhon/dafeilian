# 更新、回退与配置恢复

先确认插件安装在 `web` 还是官方桌面端的 `desktop` profile。使用命令操作前完全退出对应 Host，包括托盘或后台仍在运行的进程；操作完成后重新启动。使用应用内插件管理时，按应用提示重启。

大肥镰统一从 `https://github.com/linzhenhon/dafeilian.git` 安装和更新。自 `v0.0.1` 起包名和插件 ID 为 `dsh-dafeilian`；旧接口、环境变量和数据目录继续兼容 `dsh-dafeiyu`。

## WebUI

全局 CLI：

```powershell
dsh plugin --profile web update dsh-dafeilian
```

`npx` 用户：

```powershell
npx -y @deepseek-ai/dsh plugin --profile web update dsh-dafeilian
```

从 DeepSeek Harness 源码启动的用户，在 Harness 仓库中执行 `pnpm dsh plugin --profile web update dsh-dafeilian`。

如果 `update` 没有取得仓库最新提交，移除后按 Git 地址重新安装：

```powershell
npx -y @deepseek-ai/dsh plugin --profile web remove dsh-dafeilian
npx -y @deepseek-ai/dsh plugin --profile web add "https://github.com/linzhenhon/dafeilian.git"
```

## 官方桌面端

官方桌面端暂不支持应用内自动更新时，打开左侧 **插件**，卸载 **dsh-dafeilian**，再通过 **添加插件** 输入 `https://github.com/linzhenhon/dafeilian.git`，安装后点击 **立即启用**。从旧版迁移时，先卸载旧条目 **dsh-dafeiyu**。若应用提示刷新或重启，按提示操作。

命令方式必须使用**桌面应用自带的 CLI**。先启动一次应用初始化 profile，完全退出，再执行：

```powershell
dsh plugin --profile desktop update dsh-dafeilian
```

命令入口是安装目录中的 `resources/runtime/cli/bin/dsh`（Windows 为 `dsh.cmd`）；提供命令注册的版本也可从应用菜单注册它。独立 npm / `npx @deepseek-ai/dsh` 的 CLI 不能修改官方 Desktop profile。[上游安装归属说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.zh.md#bundled-command-runtime)。

第三方桌面壳可能仍连接 `web` profile，需按实际 Host 判断。

## 从本地克隆重新安装

当前仓库没有独立 `.tgz` Release。可以先克隆仓库，再从仓库根目录安装：

```powershell
git clone https://github.com/linzhenhon/dafeilian.git
cd dafeilian

# WebUI
npx -y @deepseek-ai/dsh plugin --profile web add .

# 官方桌面端，自带 CLI
dsh plugin --profile desktop add .
```

GitHub 自动生成的 **Source code (zip / tar.gz)** 是源码归档，不是经过项目工作流构建的安装包。

## 有意回退（仅排错）

确需排错回退时，可以安装本仓库的明确提交：`git+https://github.com/linzhenhon/dafeilian.git#<commit>`，其中 `<commit>` 替换为完整提交哈希。不要用历史上游版本号作为大肥镰的一般安装建议；升级 DSH 后回退到旧提交，可能重新遇到设置接口兼容问题。

## 移除

```powershell
# WebUI
npx -y @deepseek-ai/dsh plugin --profile web remove dsh-dafeilian

# 官方桌面端，自带 CLI
dsh plugin --profile desktop remove dsh-dafeilian
```

## DSH 迁移后角色大小恢复默认（#76）

该报告中，旧 `settings.yaml` 的大肥鱼配置没有进入新 profile 的 `cordis.patch.yml`。角色启动参数因此得到默认大小；本地位置文件里保留的旧大小不会覆盖 Host 的明确配置。

新的实时设置适配可保存今后的修改，**不会自动找回已经丢失的历史配置**。安装包含修复的版本后，在大肥鱼设置页重新设置并保存原来的角色大小、气泡大小等值，再重启验证。

如果设置页暂时无法使用，可以在退出 Host 并备份用户配置后，将旧值合并到**对应 profile 的用户 patch**。默认位置为 `~/.dsh/profiles/web/cordis.patch.yml` 或 `~/.dsh/profiles/desktop/cordis.patch.yml`；设置了 `DSH_HOME` 时以该目录为准。

```yaml
- id: dsh-dafeilian
  config:
    scale: 0.6
    bubbleScale: 0.8
    activityLevel: lively
    includeSubagents: true
```

以上仅为示例，请用自己的旧值和实际插件条目 ID。合并到已有同 ID 条目的 `config`；没有对应覆盖条目时再追加。保留文件中其他插件配置，勿用示例覆盖整个文件，也不要修改 npm 包内的默认 `cordis.patch.yml`。若旧文件已被上游迁移重命名，可检查 `settings.yaml.imported` 等备份。

## Windows `EPERM` / `EBUSY`（#66）

更新前必须完全退出相关 Host；如果同时运行 WebUI 和 Desktop，分别确认其后台进程已退出。Git 源码安装没有预编译 Helper，但 pnpm 仍可能因插件目录被 Host 占用而报告文件锁。

如果再次失败，保留包含**实际被锁定路径**的完整安装日志。只看到 `[exit 1]` 不足以区分文件锁、包管理器、网络和兼容性检查问题。不要通过删除整个 DSH profile 排错，以免丢失设置和会话。

## 角色不出现 / Helper 启动失败（#88、#91）

Helper 的启动过程会写入诊断日志，超时、`exited before ready`、`spawn error` 和最终放弃都会留下原因：

- Windows：`%LOCALAPPDATA%\dsh-dafeiyu\logs\helper.log`
- macOS：`~/Library/Logs/dsh-dafeiyu/helper.log`
- Linux：`${XDG_STATE_HOME:-~/.local/state}/dsh-dafeiyu/helper.log`

本 Git 仓库不包含 `runtime/bin/` 中的预编译 Helper，Windows、Linux 和未自行构建 Swift Helper 的 macOS 会回退到 Python。需要给运行 Host 的 Python 安装 `PySide6>=6.7,<6.12`（`python -m pip install "PySide6>=6.7,<6.12"`）；必要时设置 `DSH_DAFEIYU_PYTHON=<python 可执行文件路径>`。日志和 console 会写出架构与缺失依赖，而不是静默重试后放弃。

需要改变日志位置时设置 `DSH_DAFEIYU_LOG_FILE=<路径>`，设为 `off` 可关闭。日志只包含本地路径与 Helper 的启动/错误信息，不包含凭据。

## 右键菜单改大小后重启回退（#95）

为兼容旧安装，`v0.0.1` 继续把右键菜单选择的大小、气泡大小和「减少动态」记到 `$DSH_HOME/dsh-dafeiyu/user-settings.json`（默认 `~/.dsh/dsh-dafeiyu/user-settings.json`）。这是 DSH `settings.update()` 写不进去时的兜底：

- 只要 DSH 里仍是选择时的旧值，helper 重启或 DSH 重启后仍沿用菜单选择；
- 之后在 DSH 设置页改成新值时，兜底会自动清除，新值优先；
- 删除这个文件可以放弃兜底、回到 DSH 设置页的值。

同时失败原因会写到 Helper 日志（路径见上一节）。如果 DSH 设置页本身保存失败，设置页仍会报错；请把 Helper 日志里 `settings.update failed` 那一行附到 issue，里面会带请求的 namespace 和 host 实际暴露的 namespace。

## 更新通知

在[大肥镰 GitHub 仓库](https://github.com/linzhenhon/dafeilian)选择 **Watch** 接收更新通知。Star 只收藏项目。
