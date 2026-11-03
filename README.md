# Collect 抖音口播采集与金山追加

当前状态：**testing**。已启用 Windows 每两天一次的任务，首次执行为 **2026年11月4日09:00（北京时间）**。三个账号的独立副本追加、原格式保护、正常授权媒体保存及本地转写已验证；尚未完成首条真实新增稿的正式定时写入和至少24小时观察，不能标记 production_ready。

## 当前会做什么

监测示例账号3、示例账号2、示例账号1。使用另一个账号登录的专用 Edge 浏览器查看公开作品，不要求三个目标分别 OAuth 授权。身份使用已核实主页 sec_uid，不依靠昵称搜索结果猜测；OAuth open_id 是另一种标识，不能混用。

只处理点赞**严格大于500**的作品。以金山文档中各账号最后收录日期为增量基线，优先追加尚未收录的最新达标作品，并复查已观察到低于阈值、后来跨过阈值的旧作品。不会批量重新导入全部旧作品。文档内已存在的10月22日样本已标记 already_present，不重复追加或替换。

正式文档现有文字、格式、统计数字全部保留。新稿只追加在对应账号分区末尾，不删除、不重排、不更新旧记录。目标为 https://www.kdocs.cn/l/example-document 。

## 新稿排版

```text
2026年11月3日，点赞501 评论7 收藏20 分享3；
口播视频
作品标题
第一段完整正文……

第二段完整正文……
```

日期使用作品发布日期，统计值取详情页当次显示。缩写原样保留，缺失写“待获取”，绝不填假0。正文合并ASR碎行，每段后只空一行，不文学改写或扩写。不把账号、链接、采集时间、识别说明、校对说明或归档标识放进正文；这些信息存于本地数据库和旁路元数据。

## 自动执行的条件

电脑需要开机且当前 Windows 用户保持登录；关闭 Codex 不影响任务。关机、休眠或注销期间无法执行，恢复可用后由 StartWhenAvailable 补跑。运行时使用专用 Edge 配置，请勿同时打开 browser-probe 或 wps-login 占用同一配置。

Windows任务名：`DouyinViralCollect`。默认每两天北京时间09:00，普通用户权限运行，不要求管理员。任务直接启动 `.venv/Scripts/python.exe scripts/scheduled-run.py`，不依赖后台Agent或n8n。

浏览器登录过期、验证码、限流或异常跳转会暂停并记录，不绕过。仅保存页面正常请求、已授权可访问的音视频，使用标准HTTP字节范围读取；不调用私有接口、不生成平台签名、不处理DRM、不在403后换身份绕过。保存后校验音轨、完整性及与当前作品播放器的时长一致。用户提供的本地原文件优先。无法取得合法素材则 waiting_media，不能编造口播。

目前自动取音轨针对视频。图文使用本人提供或有权访问的本地图片做顺序OCR；尚无可靠图片源时等待，不把发布描述冒充图片内全部文字。

## 文档安全与已做验证

已从金山正常下载入口备份原格式DOCX。正式文档与最初备份的SHA256完全一致，原有文字、段落属性、样式、字体和页面设置未改动。

另存的私有独立测试副本为“Collect追加验证副本20261102”。在三个账号分区均用实际适配器验证了长中文分段追加，下载前后文件核验新增全文完整、所有旧段落及格式保留。该副本内有测试标记，正式文档没有测试内容。

每次正式追加前重新下载原格式备份，严格核对账号标题唯一性；写后再下载并逐段比较，只允许在目标分区边界增加新段落。旧字、旧格式、页设置或样式发生变化，或新正文不完整，就不能认定成功。

写入前把尝试持久记录为writing，成功全文核验后才更新archived。崩溃或结果不确定为uncertain，禁止盲目重复追加；后续只尝试核验远端是否已含完整同一稿且原文安全。不能可靠确认则人工核验。相同日期且正文疑似已存在时进入duplicate_review，不冒险再写，也不因此覆盖旧稿。

写入模块、排版模板或完整性核验代码变化会使验证证明失效，必须重新在副本验证；不能只手改wps.enabled绕过。

## 常用命令

在本项目目录打开PowerShell：

```powershell
.\.venv\Scripts\collect.exe status
.\.venv\Scripts\collect.exe doctor
.\.venv\Scripts\collect.exe logs
.\.venv\Scripts\collect.exe videos
.\.venv\Scripts\collect.exe check
.\.venv\Scripts\collect.exe process --retry
.\.venv\Scripts\collect.exe archive
.\.venv\Scripts\collect.exe backup
```

`run` 执行监测、转写、归档整轮；正式开关启用后 archive/run 会追加真实新稿，不能把它们当成纯预览。`browser-check --max-scrolls 4 --max-details 30` 可控制扫描预算。`backfill`/`browser-backfill`扫描历史，但当前增量策略仍会排除不应补录的旧稿。`browser-export`仅导出发布描述到data/publishing-copy，不含逐字稿/图内OCR，不标记远端成功。

所有业务结果输出JSON。ok=true仅表示命令完成，必须查看remote、monitor、各条status；本地文件不等于金山写入成功。服务核心为Service.run，未来HTTP/n8n复用相同逻辑。

```powershell
Get-ScheduledTask -TaskName DouyinViralCollect
Get-ScheduledTaskInfo -TaskName DouyinViralCollect
Disable-ScheduledTask -TaskName DouyinViralCollect
Enable-ScheduledTask -TaskName DouyinViralCollect
```

暂停后恢复前先 doctor，确认代码证明有效、登录和未决写入已核验，不强行重试uncertain条目。更改频率用 `scripts/install-task.ps1 -Days 2 -At '09:00' -Enable`，会保留已登记的同频率首次时间。未带Enable默认注册为禁用状态，避免未验收就写正式文档。卸载用scripts/uninstall-task.ps1。

## 日志和文件

- `data/scheduler/last-run.json`：真实定时执行结果；没有该文件说明正式整轮尚未执行。preflight.json只是只读预检，不能当作已更新文档。
- `data/collect.sqlite3`：账号、作品、点赞、处理状态、基线、错误及WPS写入日志。
- `data/transcripts/<标识>/raw.txt`、cleaned.txt、recognition.json：原始识别、整理稿、时间戳与证据。
- `data/outbox/*.md`：简洁排版的本地稿，metadata.json保存旁路标识；revisions保留旧版本。
- `data/wps-backups/`：原格式备份；`data/wps-write-evidence/`：各次追加前后备份及核验结果。
- `data/wps-inspection/production-readiness.json`：副本验证证明；名字并不表示已经production_ready。

机器识别可能有同音字、人名、数值误差，内部保持machine_unreviewed。原文完整保留，OpenCC只作繁简规范化，日常不用LLM。可选字幕辅助工具scripts/extract-subtitles.py只作本地OCR证据，抽样不等于完整逐字听校，字幕区域需按视频实际位置核对；不在定时流程中默认启用。

## 登录失效与素材映射

抖音登录：运行scripts/browser-probe.ps1，在弹出的Edge自行登录并按提示回车。金山登录：运行scripts/wps-login.ps1，自行登录有编辑权限的账号后回车。密码、验证码、Token不发送到聊天；浏览器会话文件不分享。

本地素材放在原始素材文件夹，使用作品ID/链接与本地文件显式映射。导入JSON数组字段为account_id（浏览器模式使用douyin-public:加sec_uid）、id、likes、title、description、published_at、url、type（video/image）、media（本地路径数组）。多图按数组顺序处理。CSV单文件media可为字符串；多图建议JSON。不会按相似文件名或发布时间自动猜测；相对路径按项目配置目录管理。

配置为config.json，数据在data，不放临时目录。accounts字段仅供可选官方OAuth路径；当前浏览器模式使用public_profiles，不需填空open_id。官方video.list/video.data仍需申请及每个账号授权，本项目未验证这些真实凭证，不把普通作品列表接口当下载接口。

## 安装和更新

新电脑建议从python.org安装Python3.10或更高版本。当前项目虚拟环境的基础解释器来自本机Codex附带运行时；关闭Codex不影响，但长期维护建议改用独立Python，更新基础解释器前先备份并重建环境。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
.\.venv\Scripts\python.exe -m pip install -e ".[browser,media]"
.\.venv\Scripts\python.exe .\scripts\download-model.py
.\.venv\Scripts\collect.exe test
.\.venv\Scripts\collect.exe doctor
```

`py`不可用时安装脚本支持-PythonExecutable完整路径。media依赖含FFmpeg组件，无须管理员或系统PATH；优先系统FFmpeg，否则使用imageio-ffmpeg。Whisper small模型约461MiB，固定下载提交并SHA256校验，支持标准HTTP Range断点续传。只读本地模型，本机CPU int8最多4线程。

更新步骤：暂停任务，备份config.json和整个data，再更新代码与依赖、跑test/doctor，在副本复核发生变化的写入代码，最后恢复任务。模型、原始素材、登录态和数据库不提交Git，不硬编码密钥。

每日执行run时进行SQLite在线备份，副本在data/backups，不自动删除旧备份。恢复先暂停任务、关闭所有collect连接，备份整个data；把有效备份复制为collect.sqlite3，旧-wal和-shm移到独立备份目录，不混用旧WAL。恢复旧库后先核对远端与写入日志，不直接重试未决写入。缓存、素材、配置和WPS备份也需保留。

数据库schema版本1；后续版本变更需编写并测试迁移，不能把未知版本直接当兼容。迁移到其他电脑/云端需重新验证浏览器登录、GUI执行条件和文档保护，不复制会话到其他用户，不直接暴露HTTP公网。API和n8n默认未启用，见N8N_INTEGRATION.md。

## 验收与费用

- [x] 三个目标主页身份核对、公开作品和点赞真实读取。
- [x] 原始样本本地完整转写；一条正常授权播放器音轨保存及完整本地转写。
- [x] 独立测试副本三个账号分区追加、全文及原格式保护。
- [x] 每两天09:00Windows任务注册启用；Windows任务计划程序只读预检独立执行成功。
- [x] 失败、丢字、旧格式变化、未知写入结果及不重复追加等离线测试。
- [ ] 首条真实新增稿正式定时写入并核验。
- [ ] 关闭Codex后的实际整轮运行观察。
- [ ] 连续至少24小时观察，无重复归档和重大异常。

未全部满足前保持testing，不能称为production_ready。默认没有固定月费、LLM Token费或转写API费用；主要消耗本地电力、磁盘和网络下载。任何付费接口、云服务或订阅须先明确确认，本项目没有开通这些服务。

## GitHub版本记录

GitHub只保存程序、collect Skill、测试、安装脚本和说明。当前机器的config.json、配置备份、data、登录状态、原始素材、模型、转写稿和本地验收记录均不纳入Git。首次克隆后安装脚本仅在config.json不存在时复制config.example.json；示例默认关闭真实监控、文档写入和调度，不能直接替代本机已验证配置。

更新前先暂停任务并备份config.json及data；不要用git clean清除本地数据，不要强制覆盖配置。写入代码变更后需副本复验，配置及文档保护验证仍按本说明执行。常用版本命令：git status查看变化，git log --oneline查看历史，git diff查看具体修改；上传时只提交代码，核对不含素材/登录数据后再推送。GitHub同步是版本备份，不会自动更改文档、部署更新或产生付费AI调用。
