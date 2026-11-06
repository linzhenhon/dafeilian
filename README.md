<div align="center">

# DSH 大肥镰 🌾

**基于“大肥鱼”二次开发，在桌面上陪你工作的 DeepSeek Harness 伴侣。**

[安装插件](#安装) · [源码仓库](https://github.com/linzhenhon/dafeilian) · [上游项目](https://github.com/QCYTSN/dsh-dafeiyu) · [English（上游参考）](README_EN.md) · [更新日志](CHANGELOG.md)

[![GitHub](https://img.shields.io/badge/GitHub-linzhenhon%2Fdafeilian-181717?logo=github)](https://github.com/linzhenhon/dafeilian) [![Last commit](https://img.shields.io/github/last-commit/linzhenhon/dafeilian)](https://github.com/linzhenhon/dafeilian/commits/main) [![License](https://img.shields.io/badge/code-MIT-blue)](LICENSE)

</div>

> [!IMPORTANT]
> **大肥镰是 [DSH 大肥鱼](https://github.com/QCYTSN/dsh-dafeiyu) 的二次开发版本，并非上游官方发行版。** 感谢原作者与社区贡献者。当前包名和插件 ID 为 `dsh-dafeilian`，版本为 `v0.0.1`；旧的接口路径、环境变量、数据目录和 Helper 文件名暂时保留 `dsh-dafeiyu` 作为兼容层。大肥镰的安装来源统一为本仓库。代码与素材分别遵循仓库内现有许可证，详见[素材与授权](#素材与授权)。

大肥镰由 DSH 插件启动，随 DSH 一起退出。透明、无边框、始终置顶的原生窗口，让你在编辑器、浏览器或其他应用中也能看到 Agent 的工作状态。

> **推荐安装：[v0.0.1 预编译安装包](https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz)。** 可直接把该 `.tgz` URL 粘贴到插件管理器。从 Gitee 源码安装时已附带 Windows x64 预编译 Helper，Windows 用户无需额外下载 Python 依赖或授权安装脚本。

<img src="assets/pet/custom/idle_pose.png" width="300" alt="大肥镰棕色昆虫宠物形象">

*大肥镰使用仓库所有者提供并授权公开的棕色昆虫宠物形象；角色素材不适用代码的 MIT 许可证，详见[素材与授权](#素材与授权)。私人配音与渲染源文件仍保存在忽略目录，不随仓库分发。*

## 能做什么

- 显示真实任务状态：思考、查找、修改、执行、验证、等待确认、完成和错误。
- 展示项目、步骤、多任务和 DSH 提供的待办进度；没有真实进度时显示阶段。
- 在状态气泡和设置页显示 DeepSeek 余额，区分 API Key 与已登录账户。
- 可选开启币种盯盘：最多订阅五个币安 USDT 现货交易对，桌宠卡片展示所选币种在 1 分钟、15 分钟、1 小时或 4 小时 K 线内的实时涨跌，无需登录。
- 兼容 WebUI 与官方桌面端的共享客户端；两个客户端使用各自的插件配置。
- 支持拖动、摸头、戳身体、碰尾巴，以及大小、气泡、声音和减少动态设置。
- 气泡支持键盘输入、点按录音填字和持续语音通话；通话会在停顿后逐句发送到当前 DSH 对话并朗读回复。语音识别在本机运行，详见 [语音输入设置](docs/voice-input.md)。
- 可选在 DSH 页面右下角显示轻量角色，默认关闭。

状态来自 DSH 会话事件。大肥镰不会读取屏幕；推理强度与进度只显示上游实际提供的信息。

## 先选你的 DSH 客户端

| 使用方式 | 安装位置 | 设置入口（DSH 0.2） | 角色右键菜单的打开目标 |
| --- | --- | --- | --- |
| 浏览器 WebUI | `web` profile | 左侧插件 → dsh-dafeilian | WebUI，默认 `http://127.0.0.1:3080/` |
| 官方桌面端 | `desktop` profile | 左侧插件 → dsh-dafeilian | 通过 `dsh://open` 唤起桌面应用 |

**WebUI 中安装的插件不会自动出现在桌面端。** 两边都启用会各自启动原生角色，可以在其中一个 profile 关闭“大肥鱼”。第三方桌面包装器可能仍使用 `web` profile，请以它的实际启动方式为准。

客户端包中的 `platform: web` 也适用于官方桌面端：官方 Electron 应用使用同一套 Web 客户端。原生角色由对应 Host 启动。

## 安装

使用命令行安装、升级或移除前，先**完全退出对应 DSH Host**；操作后重新启动。通过桌面应用内的插件管理操作时，按应用提示重启。

普通用户安装带 Windows、Linux 和 macOS 预编译 Helper 的稳定版：

```text
https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz
```

也可以直接安装 Release 资产 `dsh-dafeilian-0.0.1.tgz`。该安装包由 GitHub Actions 在各原生平台构建并验证，正常使用不需要安装 Python、PySide6 或 Git。GitHub 自动生成的 Source code 压缩包不是插件安装包。从 Git / Gitee 源码安装时，Windows x64 使用仓库附带的 Helper；其他平台需按上文手动安装依赖。

### 浏览器 WebUI

已全局安装 DSH：

```powershell
dsh plugin --profile web add "https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz"
dsh web
```

使用 `npx`，无需全局安装 DSH：

```powershell
npx -y @deepseek-ai/dsh plugin --profile web add "https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz"
npx -y @deepseek-ai/dsh web
```

从 DeepSeek Harness 源码运行的用户，在 Harness 仓库中执行：

```powershell
pnpm dsh plugin --profile web add "https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz"
pnpm dsh web
```

### 官方桌面端

推荐直接在应用内安装：

1. 打开官方 DeepSeek Harness 桌面应用，点击左侧 **插件**。
2. 点击 **添加插件**，输入 `https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz`，点击 **安装**。
3. 安装成功后点击 **立即启用**，桌面角色会出现在桌面上。
4. 在插件列表打开 **dsh-dafeilian**，调整角色、气泡和余额设置，修改实时生效。

这套流程使用桌面应用自带的安装环境，用户无需单独安装 Node.js、Python、PySide6 或 Git。若应用提示刷新或重启，按提示操作；失败时展开 **查看安装详情** 并保留日志。

使用命令安装时：

1. 先启动一次官方桌面应用，让它初始化 `desktop` profile，然后完全退出。
2. 使用桌面应用**自带的 `dsh` 命令**。支持命令注册的版本可从应用菜单的 **Manage dsh command… / 管理 dsh 命令**入口配置；也可直接调用安装目录的 `resources/runtime/cli/bin/dsh`（Windows 为 `dsh.cmd`）。
3. 执行：

   ```powershell
   dsh plugin --profile desktop add "https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz"
   ```

4. 重新打开桌面应用，在左侧插件 → dsh-dafeilian 调整角色。

**这里的 `dsh` 必须来自桌面应用。** 独立安装的 npm / `npx @deepseek-ai/dsh` CLI 不能修改官方桌面端的 profile。请参考 [DSH 官方桌面端说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.zh.md#bundled-command-runtime)。

### 从本地克隆安装

Gitee 源码仓库包含 Windows x64 预编译 Helper；此平台安装无需 Python 或额外依赖下载。其他没有预编译 Helper 的平台需预先安装 Python 3 和 `requirements.txt` 中的依赖。

```powershell
git clone https://gitee.com/yummy-lin/dsh-dafeilian.git
cd dsh-dafeilian

# WebUI
npx -y @deepseek-ai/dsh plugin --profile web add .

# 官方桌面端；必须使用应用自带的 dsh
dsh plugin --profile desktop add .
```

普通用户离线安装请从 [v0.0.1 Release](https://github.com/linzhenhon/dafeilian/releases/tag/v0.0.1) 下载 `dsh-dafeilian-0.0.1.tgz`，不要下载或解压 GitHub 自动生成的 **Source code (zip / tar.gz)**。

## 余额显示

余额默认出现在**桌面角色状态气泡底部和设置页**，查询逻辑由两个客户端共用。设置页可查看总余额、赠送和充值，并手动刷新。

| 来源 | 凭据来自哪里 | 查询内容 |
| --- | --- | --- |
| 自动（默认） | 优先使用 DSH 模型设置中的 DeepSeek API Key；未配置时尝试已登录账户 | 对应来源的余额 |
| API Key | DSH 的凭据服务；旧 Host 无该服务时读取启动环境 | DeepSeek `/user/balance` |
| 已登录账户 | DSH 的 DeepSeek 账户服务 | 账户充值与赠送钱包 |

- 在 **DSH 模型／账户设置**中配置凭据；插件设置页不需要再填写 API Key。
- API 余额与账户余额分别标明来源；CNY / USD 分别显示。
- 每分钟自动刷新，同一 Host 内共享缓存；手动刷新最快每 5 秒一次。
- 服务失败时保留上次成功结果，并标明“上次查询”；未配置、授权失败和网络失败分别提示。
- 自定义网关需要实现相同的 `/user/balance` 接口；不支持时显示查询失败。
- API Key、登录凭据和上游原始错误不会进入余额页面、角色消息或事件流。
- 没有余额凭据也能正常显示任务状态；可关闭“显示 DeepSeek 余额”。

账户余额和 API 余额的查询方式参考了 [keshing/balance-display](https://github.com/keshing/balance-display) 与 DSH 的公开账户服务。余额查询不会发起模型调用。

## 常用设置

| 设置 | 作用 |
| --- | --- |
| 启用大肥鱼（当前兼容名称） | 开关当前 profile 的原生角色 |
| 角色大小 / 气泡大小 | 独立调整；小气泡保留基本字号 |
| 待机文案 | 修改桌宠待机气泡的标题，输入后点击“保存”或按回车，立即生效；默认“小弟陪大哥待命” |
| 安静 / 标准 / 活泼 | 每次待机动作结束后，分别休息 45～90 / 25～45 / 12～22 秒 |
| 减少动态 | 固定角色姿势，停止待机与点击动画；状态和提示仍实时更新 |
| 提示音 | 所有提示的总开关（只影响声音） |
| 提示音版本 | 在公开版的 A、B、C 三套合成音效间切换；编辑页面可分别试听完成、出错、等待审批提示，也可上传经授权的自定义音频；桌宠右键「声音」也可切换并开关提示音 |
| 提示音与通知场景 | 分别开启“对话完成”“工具出错”“等待审批”提示。取消后该场景不再播放声音；macOS 同时不再弹系统通知横幅，Windows / Linux 只播放声音 |
| 气泡显示 | 常驻、隐藏，或仅在指定状态显示 |
| 子 Agent | 允许子 Agent 状态参与显示 |
| 页面内角色 | 在 DSH 页面右下角显示轻量角色 |
| 打开目标 | 自动、WebUI 或官方桌面端 |
| 显示余额 / 余额来源 | 开关与选择余额查询来源 |
| 炒币盯盘动作 | 最多订阅五个币安 USDT 现货交易对，在桌宠卡片选择一个展示；可选 1m、15m、1h、4h 周期，无需登录或 API Key |
| 摸鱼模式（看小说，Windows / Linux Qt Helper） | 导入自己的 TXT 小说，在桌面阅读窗口用方向键或滚轮翻页，自动保存进度 |
| 下象棋（Windows / Linux Qt Helper） | 点击卡片底部「下象棋」与宠物对弈；进入时收起原卡片，退出时恢复 |
| 看视频（Windows / Linux Qt Helper） | 选择本地视频和宠物一起看，支持暂停、跳转进度、音量与静音 |
| 内嵌抖音（Windows） | 在「看视频」窗口切换抖音，通过官方页面扫码登录，查看自己的账号内容 |

设置页修改实时生效。请直接使用桌宠气泡中的输入框，将任务排队发送到当前打开的 DSH 对话；发送失败时输入内容保留，可修改后重试。右键菜单保留语音录入、语音通话、大小、减少动态、声音、打开对应 DSH 客户端，以及仅在本次运行隐藏／关闭角色等操作。

盯盘使用币安公开现货 WebSocket K 线流。涨跌幅按所选周期当前 K 线的开盘价计算；最多订阅五个币种，只在桌宠卡片显示当前选中的一个。连接会自动轮换币安的 9443、443 端口和仅提供公开行情的备用域名。若桌宠持续显示“重试”，请检查当前网络或代理是否能访问币安行情域名。具体接口见[币安 K 线 WebSocket 文档](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#klinecandlestick-streams)和[公开行情备用域名说明](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)。

点击动作会完整播完，再回到当前任务状态；新任务可立即打断装饰动作。拖拽期间只播放悬空姿势，松手后完整落地。具体触发、频率和衔接规则见 [动作说明](docs/animation-behavior.md)。

若 WebUI 使用自定义地址，可在启动 Host 时设置 `DSH_DAFEIYU_WEBUI_URL`；它优先于自动推断的默认地址。

### 摸鱼模式（看小说）

在插件设置页的「摸鱼模式（看小说）」区域点击「导入 TXT 小说」，或右键桌宠 →「摸鱼模式（看小说）」→「导入 TXT 小说…」。支持 UTF-8、GB18030 和带 BOM 的 UTF-16，文本转换为 UTF-8 后不超过 10 MB。导入后自动启用阅读动作并打开阅读窗口；关闭阅读窗口后宠物仍继续看书，可从右键菜单再次打开。

默认手动翻页：阅读窗口获得焦点后，按 `↑` / `Page Up` 翻上一页，按 `↓` / `Page Down` 翻下一页；鼠标移到阅读窗口内，滚轮向上翻上一页，向下翻下一页。方向键也可在窗口内按钮获得焦点时使用，连续按键和滚动会按顺序处理；首页、末页不会越界。这些操作只在阅读窗口内生效，任务执行期间仍可手动阅读。

开启「自动翻页」后，可在设置页选择每 10、20、30 或 60 秒翻一页。宠物处理任务、提示完成或出错、录音通话及拖拽期间暂停自动翻页，回到空闲后继续；读到最后一页自动停止。关闭「开启摸鱼阅读」即可停止阅读模式。

小说和阅读进度只保存在 `$DSH_HOME/dsh-dafeiyu/novel-reader/`（默认 `~/.dsh/dsh-dafeiyu/novel-reader/`），不会发送到模型服务。只使用用户自行导入的内容，不附带小说。原生 macOS Swift Helper 暂不显示阅读动作，设置页仍可导入和手动阅读。

### 与宠物下象棋

点击桌宠卡片底部的「下象棋」，或右键桌宠 →「下象棋」。原来的任务状态、盯盘和输入卡片会收起，棋盘显示在宠物旁边，宠物进入对弈动作。你执红先行，点击红棋后再点击绿色落点；宠物使用本地对手回棋，无需联网或模型 API。

棋盘提供「悔棋」「重新开局」「收起棋盘」。普通落子、吃子、将军和胜负会播放不同的短音效，受桌宠右键菜单「声音 → 播放提示音」总开关控制。关闭棋盘或按 Esc 也会退出对弈并恢复原卡片，未发送的任务和附件保留。再次打开时继续当前棋局；重启桌宠后重新开局。进入棋局会结束正在进行的录音或语音通话，并暂停小说阅读。

实现[中国象棋的基本走法及胜负规则](https://www.xiangqi.com/how-to-play-xiangqi)，包括蹩马腿、塞象眼、炮架、九宫、将帅照面限制和应将；将死或困毙判负。休闲对弈中三次重复局面直接和棋，不进行比赛级长将、长捉裁决。原生 macOS Swift Helper 暂不支持此模式。

### 和宠物一起看视频

点击卡片底部「看视频」，或右键桌宠 →「看视频」，再点击「选择视频」打开自己的 MP4、MKV、WebM、AVI、MOV 等本地文件。进入后原卡片收起，播放器显示在宠物旁边，宠物会看着小屏幕轻轻晃动。开启「减少动态」时保持静态观看姿势。实际能否播放取决于视频的编码格式；不支持时会显示错误，可重新选择文件。

支持播放／暂停、拖动进度、音量、静音；空格播放或暂停，左右方向键快退或快进 5 秒，Esc 或「收起视频」退出。退出时暂停播放并恢复原卡片，保留任务草稿和附件；当前桌宠进程中再次打开会保留视频和进度，等待手动继续。切换下棋、小说或语音模式也会暂停视频。视频直接从所选文件播放，不复制或上传；原生 macOS Swift Helper 暂不支持此模式。

### 在视频窗口查看自己的抖音

打开「看视频」后点击「抖音 · 扫码登录」，再点击内嵌工具栏的「扫码登录」。程序会打开[抖音官方网站](https://www.douyin.com/)，并点击网页原有的登录按钮；二维码由抖音生成，你需要使用自己的手机抖音扫码并确认。登录后可在抖音网页中查看自己的个人主页、关注和推荐内容，浏览和账号操作均由官方网页提供。

Windows 使用系统的 [Edge WebView2 网页内核](https://www.qt.io/blog/using-the-webview-module-with-c-and-qt-widgets)，源码运行需要 PySide6 6.11+。登录所需的 Cookie 和网站存储由浏览器保存在布局文件所在目录的 `douyin-browser/` 中，与系统浏览器资料分开；程序不提取密码、验证码或登录凭据。可以点击「清除本机登录」清除内嵌浏览器 Cookie，或在抖音网页里退出账号。登录有效期及扫码验证要求由抖音决定。

切回本地视频、收起播放器或进入其他模式时，内嵌网页会被停用以停止播放；再次打开后通过保留的浏览器存储恢复会话。网络失败时可点击「刷新」。内嵌抖音暂不支持 Linux 和原生 macOS Helper，本地视频模式仍可使用。

## 平台与运行环境

| 平台 | `v0.0.1` Release 安装包 |
| --- | --- |
| Windows 10 / 11 x64 | 内置预编译 Helper；WSL2 可通过 Windows 互操作启动 |
| Linux x64 | 内置预编译 Helper，需要图形桌面 |
| macOS 12+ | 内置通用 arm64 / x86_64 Swift / AppKit Helper |

Gitee 源码包含 Windows x64 预编译 Helper，Windows x64 用户无需安装 Python、PySide6 或从外部下载运行依赖。Linux arm64 和其他没有预编译 Helper 的环境会回退到 Python Helper；请在安装插件前手动安装 Python 3 和 `requirements.txt` 中的依赖：

```powershell
python -m pip install -r requirements.txt
```

若 DSH 没有找到正确的 Python，可在启动 Host 前设置 `DSH_DAFEIYU_PYTHON=<python 可执行文件路径>`。也可以从源码自行构建平台 Helper。macOS Helper 需要 Xcode Command Line Tools；当前仍需真实机器验证视觉效果与多屏操作。

原生角色显示在 **Host 所在的桌面**：远程服务器、无图形环境和浏览器客户端不在同一台机器时，请先确认 Host 的运行位置。页面内角色可在浏览器中显示。

## 更新与排错

WebUI 用户完全退出 DSH 后执行：

```powershell
npx -y @deepseek-ai/dsh plugin --profile web update dsh-dafeilian
```

如果更新后仍停留在旧版本，先移除再安装明确版本：

```powershell
npx -y @deepseek-ai/dsh plugin --profile web remove dsh-dafeilian
npx -y @deepseek-ai/dsh plugin --profile web add "https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz"
```

官方桌面端暂不支持应用内自动更新时，在插件页面卸载 `dsh-dafeilian`，再输入 `https://github.com/linzhenhon/dafeilian/releases/download/v0.0.1/dsh-dafeilian-0.0.1.tgz` 安装并立即启用；也可以完全退出应用后使用自带的命令：

```powershell
dsh plugin --profile desktop update dsh-dafeilian
```

然后重新启动对应客户端。回退、移除、DSH 迁移后恢复大小，以及 Windows `EPERM` 的处理见 [更新与回退](docs/UPDATING.md)。

- DSH 0.2 设置页变化：从本仓库安装当前 `main`，通过左侧插件 → dsh-dafeilian 打开设置；较旧 Host 保留原设置入口。
- 桌面端安装只显示 `[exit 1]`：该信息不足以确定原因，请附上插件安装详细日志（如 `hub.log`）、DSH 版本、系统和安装方式。
- Release 安装失败：确认能够访问 npm；也可从 [v0.0.1 Release](https://github.com/linzhenhon/dafeilian/releases/tag/v0.0.1) 下载 `.tgz` 后通过 CLI 安装本地文件。
- 余额查询失败：检查 DSH 中的凭据及所用网关是否支持余额接口。
- 角色不出现：Release 包不依赖 Python；先检查 profile、插件是否启用、Host 是否有可用图形桌面，并查看 Helper 日志。只有 Git 源码安装才需要确认 Python 已安装 `PySide6>=6.7,<6.12`。为兼容旧安装，Helper 的日志目录暂时沿用旧名称：
  - Windows：`%LOCALAPPDATA%\dsh-dafeiyu\logs\helper.log`
  - macOS：`~/Library/Logs/dsh-dafeiyu/helper.log`
  - Linux：`${XDG_STATE_HOME:-~/.local/state}/dsh-dafeiyu/helper.log`

  Git 源码安装使用 Python Helper，不会执行预编译 Helper 的首次解压流程。需要更详细输出时可用 `DSH_DAFEIYU_LOG_FILE=<路径>` 改日志位置，或设为 `off` 关闭；报告问题时可以附上该日志（只含本地路径与启动错误，不含凭据）。

[GitHub issue / PR 处理清单](docs/GITHUB_TRIAGE.md)记录历史上游问题和处理依据；[验收记录](docs/ACCEPTANCE.md)保留已有测试结果。这些记录中的旧版本号和上游链接仅用于追溯，不是大肥镰的安装地址。

## 源码开发

```powershell
git clone https://gitee.com/yummy-lin/dsh-dafeilian.git
cd dsh-dafeilian
pnpm install --frozen-lockfile
npm test
npm run test:python
npm run build:helper
npm run test:helper:packaged
```

开发 Python Helper 需要 `requirements.txt` 中的依赖；macOS Helper 需要 Xcode Command Line Tools。纯 Swift 核心测试运行 `swift test`。修改原生代码后应重新构建 Helper，再安装本地打包产物。

CI 还会隔离安装 DSH 0.2.0-rc.2 并运行 `scripts/test-dsh-settings.mjs`，验证新设置接口。该检查不读取用户 profile 或凭据，文件写入使用测试适配器。

本仓库保留 GitHub Actions 测试与发布工作流；当前用户安装入口仍是 `https://github.com/linzhenhon/dafeilian.git`。维护者操作见 [发布说明](docs/RELEASING.md)。正式发布独立 npm 包或 `.tgz` Release 前，应先完成包名、版本、许可证和发布权限配置；禁止在本地运行 `npm publish`。

## 素材与授权

公开源码默认使用仓库所有者提供并授权公开的棕色昆虫宠物形象，动作清单为 `assets/pet-manifest-custom.json`；备用机器人保存在 `assets/pet/fallback-robot/`，非语音提示音由 `python scripts/generate_public_assets.py` 生成。私人渲染源文件和参考配音仍保存在本机忽略目录 `local-private-assets/`，不随 Git 或 npm 包分发。清单中的 `motionProfiles` 继续控制待机、思考、工作、等待、拖拽和点击动作。上游 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 动画帧保留在源码目录作参考，不进入 npm 包；其角色形象为 CC BY-NC-SA 4.0，动画素材禁止商用。

软件代码与角色素材适用不同授权，请阅读中英双语的 [ASSET_LICENSE.md](ASSET_LICENSE.md)、[上游代码许可证](assets/dsh-pet-LICENSE.txt)和 [LICENSE](LICENSE)。旧版素材及社区拖拽图片仅留在本机 `legacy/`，不进入公开提交或 npm 包。

感谢社区在动画、macOS、WSL 和兼容性方面的贡献。想接收更新通知，请订阅仓库 **Watch → Custom → Releases**；Star 只收藏项目。
