# 素材授权说明 / Asset License Notice

## 中文

本仓库的**代码**采用 [MIT 许可证](LICENSE)。代码授权不自动覆盖角色形象、动画、录音、截图和第三方素材。公开发布时，应分别确认每类素材的权利。

| 素材 | 位置 | 授权与公开范围 |
| --- | --- | --- |
| 大肥镰棕色昆虫宠物形象 | `assets/pet/custom/` | 由仓库所有者 `linzhenhon` 提供并确认拥有公开发布权。**© 2026 linzhenhon，保留所有权利。** 允许随本项目查看、下载和运行；未经权利人另行许可，不得将角色素材单独复制、修改、再分发或商用。代码的 MIT 许可证不适用于这些图片。 |
| 原创备用机器人与合成提示音 | `assets/pet/fallback-robot/`、`assets/sounds/` | 由 [`scripts/generate_public_assets.py`](scripts/generate_public_assets.py) 使用绘图指令和合成音生成，不使用私人参考图、录音或上游角色画面；随本仓库按 MIT 许可证提供。公开版三套提示音都是**非语音音效**。 |
| 上游 dsh-pet 动画帧 | `assets/pet/` 中的 WebP、`assets/pet-manifest.json` | 从 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的动画转换而来，保留作源码参考，不进入 npm 包。上游说明：代码 MIT；动画、提示词和源视频允许开源使用、禁止商用；角色形象采用 **CC BY-NC-SA 4.0**。衍生作品公开时应署名并链接上游仓库，遵守非商业与相同方式共享要求。不能把这些角色帧当成 MIT 素材使用。导入版本固定在上游提交 [`549fff2`](https://github.com/PC2005-cloud/dsh-pet/tree/549fff2ea33c2acfb16612c76912c6137da4a758)；具体来源及帧窗口见清单。 |
| Chromium 手形光标 | `assets/cursor_grab.cur`、`assets/cursor_grabbing.cur` | Chromium Authors 的 **BSD 3-Clause** 素材；来源、许可证和文件摘要见 [`assets/cursors/`](assets/cursors/README.md)。 |
| 私人渲染源图与授权参考录音 | 本机忽略目录 `local-private-assets/`；其他原始录音在 `local-audio/` | 除上述 17 张已获确认并发布的运行姿势图外，其余渲染源图、配音和参考录音**不进入 Git、npm 包或公开仓库**。本机备份仅供使用者自行保存；公开或商用前须另行确认相关图像、表演者和声音权利。 |
| 旧版大肥鱼与社区拖拽图 | 本机 `legacy/dafeiyu/` | 权利限制与公开再分发许可不明确，因此从公开提交和 npm 包中排除。图像处理或缩放不改变原作品权利。 |
| 旧版界面截图 | 本机 `docs/images/` | 可能含有旧版角色画面；从公开提交和 npm 包中排除。 |

上游 dsh-pet 的[许可与角色说明](https://github.com/PC2005-cloud/dsh-pet#许可)是这些动画的依据；[`assets/dsh-pet-LICENSE.txt`](assets/dsh-pet-LICENSE.txt)记录的是上游**代码**的 MIT 文本，不代表动画或角色形象也采用 MIT。该桌宠为非官方同人项目，与 DeepSeek 无隶属或背书关系。各名称、商标和角色权利仍归原权利人。

公开版的声音设置仍保留三个音效槽位，便于本机加载经授权的私人配音；公开包本身没有男声、女声或用户翻唱录音。提交前请再次用 `git status` 与 `npm pack --dry-run` 检查将公开的文件。

## English

The **source code** is available under the [MIT License](LICENSE). That license does not automatically apply to character designs, animation, recordings, screenshots, or third-party assets. Verify the rights for each asset class before publishing.

| Asset | Location | License and publication scope |
| --- | --- | --- |
| Dafeilian brown insect mascot | `assets/pet/custom/` | Supplied by repository owner `linzhenhon`, who confirmed the right to publish it. **© 2026 linzhenhon. All rights reserved.** It may be viewed, downloaded, and run as part of this project. The character assets may not be separately copied, modified, redistributed, or used commercially without additional permission from the rights holder. The code's MIT license does not cover these images. |
| Original fallback robot and synthesized alerts | `assets/pet/fallback-robot/`, `assets/sounds/` | Generated from drawing primitives and synthesized tones by [`scripts/generate_public_assets.py`](scripts/generate_public_assets.py), without private references, recordings, or upstream character imagery. Provided with this repository under MIT. All three public alert sets are **non-speech sounds**. |
| Upstream dsh-pet animation frames | WebP files under `assets/pet/`, `assets/pet-manifest.json` | Converted from [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) and retained as source reference; excluded from the npm package. The upstream project licenses its code under MIT, allows open-source use of animation/prompt/source-video assets but prohibits commercial use, and identifies the character design as **CC BY-NC-SA 4.0**. Public derivatives must attribute and link the upstream repository and respect the noncommercial and share-alike conditions. These character frames are **not MIT assets**. The import is pinned to upstream commit [`549fff2`](https://github.com/PC2005-cloud/dsh-pet/tree/549fff2ea33c2acfb16612c76912c6137da4a758); see the manifest for source hashes and frame windows. |
| Chromium hand cursors | `assets/cursor_grab.cur`, `assets/cursor_grabbing.cur` | **BSD 3-Clause**, copyright The Chromium Authors. Provenance, license, and file hashes are in [`assets/cursors/`](assets/cursors/README.md). |
| Private render sources and voice-reference recordings | Ignored local directory `local-private-assets/`; other source audio in `local-audio/` | Except for the 17 approved runtime poses described above, render sources, voice recordings, and reference audio remain **excluded from Git, npm, and the public repository**. Confirm all relevant image, performer, and voice rights before any additional public or commercial use. |
| Legacy BigFish and community drag images | Local `legacy/dafeiyu/` | Public redistribution rights are unclear, so these files are excluded from public commits and npm packages. Resizing or re-encoding does not change underlying rights. |
| Old interface screenshots | Local `docs/images/` | May depict the legacy character; excluded from public commits and npm packages. |

The upstream [license and character notice](https://github.com/PC2005-cloud/dsh-pet#许可) governs its animation assets. [`assets/dsh-pet-LICENSE.txt`](assets/dsh-pet-LICENSE.txt) reproduces the upstream **code** MIT license; it does **not** extend MIT to the animation or character. This is an unofficial fan project, neither affiliated with nor endorsed by DeepSeek. Names, marks, and character rights remain with their respective owners.

The public package retains three alert slots for locally supplied, authorized voice recordings. It contains no male or female voice recording and no user cover-song audio. Before committing or packing, inspect `git status` and `npm pack --dry-run` again.
