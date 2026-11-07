# Collect · 抖音口播文稿整理助手

**选账号、设点赞门槛，把口播和图文整理成自己的 Word 文稿库。**

适合整理自己的创作存档，或有权使用的公开素材。支持任意数量目标账号，默认收录**不少于 500 赞**的作品；可以改为 100、1000 等门槛，也支持严格“超过”。本地 Word 是默认出口，不需要提前创建金山文档。

## 快速开始 · Windows

1. 安装 Python 3.10 或以上和 Microsoft Edge，下载本仓库 ZIP 并解压。
2. 双击 `start.cmd`。首次会安装独立 Python 环境和本地识别依赖、下载 Whisper 模型，需联网和足够磁盘空间；根据电脑配置可能需要较长时间。
3. 输入目标账号的网页版主页链接和点赞门槛，在弹出的 Edge 中自行登录，再回到终端按回车。登录账号可以与目标账号不同。

结果保存在 `exports/`：每轮生成新 `.docx` 和整理记录，不覆盖你的手工校订。账号名分区、独立起页，宋体四号标题、宋体五号正文；每篇之间留出间距，正文自然段连续排版。没有完整且达标的正文时只输出待处理清单，不生成空文档冒充成功。

**当前采集边界：** 网页可能要求验证、限制访问或不给出可保存的完整媒体。这些作品会保留为 `waiting_media` 等待处理，不能保证每个账号一次运行就采齐。默认只执行有预算的一轮扫描，历史结果可能为 partial/stalled；不代表已穷尽所有作品。可补充自己的原视频并继续处理。无口播需先确认，再使用完整发布文案；不会把下载失败当作无口播。

## 在 Codex 中使用 Skill

在 Codex 打开解压后的**完整项目目录**，启用项目中的 `.agents/skills/collect`，例如提出：

> 帮我整理这个账号，点赞不少于 1000，先核对字幕和口播，再生成 Word，不启用共享文档。

Skill 指导 Codex 核对来源、字幕、口播与可选素材库；本地脚本负责采集、识别、记录与排版。**仅复制 SKILL.md 并不包含运行程序**；请保留完整仓库。直接双击运行得到的是本地识别结果，复杂专有名词建议在 Codex 中进一步校对；不承诺零错字。

## 命令行

```powershell
# 只安装，不立即采集
python scripts/start.py --install-only
# 首次设置，可重复 --profile 录入多个账号
.venv\Scripts\collect.exe setup --profile https://www.douyin.com/user/目标主页ID --min-likes 500
# 登录并核对目标账号昵称
.venv\Scripts\collect.exe login
# 执行一轮采集、识别和 Word 导出
.venv\Scripts\collect.exe organize
# 已有整理记录再次导出；无需登录金山文档
.venv\Scripts\collect.exe export-word
# 将自己的完整正文直接排版成 Word
.venv\Scripts\collect.exe export-word --input examples/word-records.json
# 查看待处理作品
.venv\Scripts\collect.exe videos
```

`setup --strict --min-likes 500` 表示严格超过 500；默认包含 500。旧配置 `threshold: 500` 仍保持严格超过，升级不会改变原有用户的门槛含义。现有配置会备份；输出文件已存在时拒绝覆盖。首次配置后可以在 `config.json` 调整 `browser_budgets`；预算大幅增加会延长运行时间。`browser-backfill` 可扫描更多历史，仍需检查返回的覆盖范围。

本地原始素材通过作品 ID 显式映射 `media`，带字幕画面映射 `subtitle_media`，不靠文件名猜测。JSON 导入格式见 `examples/word-records.json`。`export-word --input` 只排版用户提供的正文，不代表这些文字已经平台核验或人工听审。

## 可选：共享到金山文档

**共享文稿需要博主自己创建、上传并开启共享权限。程序不会替你自动公开文档。**

本地生成 Word 后，可以手动上传金山文档并设置分享。需要持续追加时，再显式开启 `wps.enabled`、配置你自己的链接与准确标题，在浏览器自行登录，验证编辑权限并备份、测试副本追加后使用。云端写入与本地 Word 成功分别记录；本地导出成功不表示已同步云端。详细说明见 [共享与进阶配置](.agents/skills/collect/references/advanced.md)。

## 校对与隐私

- 来源优先级：用户确认词语 → 作者字幕 → 实际口播 → 匹配的素材库。保留原始识别与对齐证据，不用参考稿补入视频没有说的内容。
- 可选开启 `proofreading.video_subtitles.enabled` 做逐帧字幕核对，需要完整视频画面；可选 CT-Punc 补标点，需自行准备配置中的模型。默认不会伪称已完成多源校对。
- `data/`、`models/`、`exports/`、`config.json` 均忽略提交；浏览器会话、链接和原稿保存在本机。请勿将这些目录上传到公开仓库。
- Whisper/OCR 在本机运行；Codex 中的额外校对使用你自己的 Codex 环境。模型下载和所选云文档服务需要网络；本项目不替你开通付费服务。
- 新安装默认**不启用定时任务**。需要定时运行时单独配置任务计划程序，并核验实际执行结果；电脑关闭、登录失效或访问验证都可能阻止更新。

## 开发验证

```powershell
python -m pip install -e ".[browser,media,proofreading]"
python -m unittest discover -s tests -q
```

本仓库提供可继续扩展的 Skill 与本地工具，平台网页变化可能需要更新适配。使用前确认你有权采集、保存及使用相应内容。
