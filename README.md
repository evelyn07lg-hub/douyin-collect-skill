# Collect：抖音口播与图文采集 Skill

使用已登录的 Edge 浏览器监测自行配置的抖音账号，将点赞严格大于阈值的作品转成口播稿或图文 OCR，并追加到自己的金山共享文档。也支持本地素材导入。阈值默认 500，每两天更新一次是可选配置。

项目处于 **testing**，不是开箱即用的生产服务。新安装默认关闭真实监控、金山写入和定时任务；每位使用者需要独立完成账号核验、登录、文档备份和副本验证。仓库不提供任何人的共享文档、账号、登录态或素材。

## 安装

需要 Windows、Microsoft Edge、Python 3.10+。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
.\.venv\Scripts\python.exe -m pip install -e ".[browser,media]"
.\.venv\Scripts\python.exe .\scripts\download-model.py
.\.venv\Scripts\collect.exe test
```

安装脚本仅在 `config.json` 不存在时复制 `config.example.json`，保留已有配置。`py` 不可用时可用 `-PythonExecutable` 指定 Python 完整路径。媒体组件使用本地 FFmpeg、Whisper 和 OCR；模型下载支持断点续传及 SHA256 校验。默认不调用付费转写或 LLM 服务。

## 填入自己的账号和共享文档

编辑项目根目录的 **`config.json`**，不要把真实信息写到 `config.example.json`。该本机文件已被 Git 忽略。

1. 将 `wps.url` 填为自己有编辑权限的金山共享文档 HTTPS 链接。
2. 将 `wps.title` 填为该文档的准确标题，用于防止误入同名或其他文档。
3. 在 `public_profiles` 填写目标账号；昵称和主页身份须在真实页面核对，不能根据链接顺序猜测。文档中对应的账号分区标题应各自唯一。
4. 浏览器采集需要将 `mode` 改为 `browser`；先保留 `wps.enabled: false`，完成下方验证再启用。

配置结构示意如下，尖括号内容须替换为自己的信息：

```json
{
  "mode": "browser",
  "public_profiles": [
    {
      "name": "账号一",
      "sec_uid": "<自己的目标账号主页 /user/ 后的标识>",
      "url": "<该账号完整主页链接>",
      "name_verified": false
    }
  ],
  "wps": {
    "url": "<自己的金山共享文档链接>",
    "title": "<自己的文档准确标题>",
    "enabled": false,
    "minimum_loaded_pages": 1,
    "preserve_existing_content_and_format": true,
    "append_by_account_section": true,
    "update_existing_entries": false,
    "append_new_entries_only": true
  }
}
```

上面只是部分字段，保留 `config.example.json` 中其余字段。核对账号页面后再将对应 `name_verified` 设为 `true`。浏览器模式使用 `public_profiles`，无需填写官方 OAuth 的 `accounts`；`sec_uid` 不能与官方 `open_id` 混用。`minimum_loaded_pages` 是加载页数下限，按自己的文档设置，不代表已经完整备份。

登录入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\browser-probe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\wps-login.ps1
.\.venv\Scripts\collect.exe status
.\.venv\Scripts\collect.exe doctor
```

在弹出的 Edge 中自行登录、处理验证码。不要提供密码或 Token，不分享 `data/browser-profile`。金山登录检查只核验目标与权限，不输入测试文字；“可评论”不等于可编辑。未配置链接或标题时拒绝核验，不会回退到其他人的文档。

## 写入前验证

正式文档已有文字、格式和统计数字全部保留。新稿只追加到对应账号分区末尾，不覆盖、不重排旧稿。

启用写入前必须下载原格式 DOCX 备份，并在独立副本用实际适配器验证各账号分区的长文追加、全文完整和旧格式保护。验证证明保存在本机 `data/wps-inspection/production-readiness.json`，不随仓库分发；必须匹配自己的正式文档和当前写入模块。完成核验并明确确认后才启用 `wps.enabled`，不能复制他人的证明或仅手改开关绕过。

每次正式追加前后下载原格式文件，逐段核对新增全文和所有旧段落、样式、字体及页面设置。 DOCX 核验允许编辑器拆分或合并相邻且字符属性完全相同的文字片段；文字、字符格式或段落属性的真实变化仍会被拒绝。写入模块或模板修改会使证明失效，需要重新在副本验证。当前适配器针对金山文字文档，其他文档类型、页面布局及权限需要实际核验；不保证只填链接即可适用于任意共享文档。

增量基线使用各账号已收录日期；后续跨过点赞阈值的已观察作品仍可处理。旧稿由本地状态及完整正文核验去重，不修改旧统计。疑似重复进入 `duplicate_review`，未知写入结果进入 `uncertain`，不自动重复写。

## 归档格式

```text
2026年11月3日，点赞501 评论7 收藏20 分享3；
口播视频
作品标题
第一段完整正文……

第二段完整正文……
```

日期为作品发布日期，统计取当次详情页显示。缺失写“待获取”，不填假 0；“万”等缩写原样保留。正文合并识别碎行，每段只空一行，不改写或扩写。账号、来源链接、采集时间、识别状态及去重标识放在本地旁路元数据中，不放入共享文档正文。

用户提供的本地素材优先；正常授权播放器音轨可自动保存并检查完整性及作品时长。不能取得素材则 `waiting_media`，不把发布描述冒充逐字稿或图片全文。图文依本地图片顺序 OCR。机器识别可能存在同音字、人名和数字误差，内部保留 `machine_unreviewed` 状态。

## 常用命令

```powershell
.\.venv\Scripts\collect.exe check
.\.venv\Scripts\collect.exe process --retry
.\.venv\Scripts\collect.exe archive
.\.venv\Scripts\collect.exe run
.\.venv\Scripts\collect.exe videos
.\.venv\Scripts\collect.exe logs
.\.venv\Scripts\collect.exe backup
```

`run` 执行监测、识别和归档整轮。启用正式写入后，`archive` 和 `run` 会操作真实文档，不能当作预览。`ok=true` 仅表示命令完成，需查看 `remote`、`monitor` 和每条处理状态；本地文件不是金山写入成功。

`browser-check --max-scrolls 4 --max-details 30` 控制扫描预算；`backfill` 和 `browser-backfill` 用于历史扫描，仍遵守增量策略。`browser-export` 仅导出发布描述，不含口播或图内全文，也不标记远端成功。

本地素材导入 JSON 数组支持 `account_id`、`id`、`likes`、`title`、`description`、`published_at`、`url`、`type`（video/image）及 `media`（本地路径数组）。浏览器账号 ID 为 `douyin-public:` 加 `sec_uid`。素材与作品需显式映射，不根据相似文件名自动猜测；多图按数组顺序处理。

登录过期、验证码、限流或异常跳转会暂停并记录。不调用私有接口、不生成平台签名、不绕过 DRM 或访问限制。官方 OAuth 是可选路径，需要各账号授权与相应开放平台权限；本项目不将普通作品列表接口视为下载接口。

## 可选定时任务

完成自己的文档验证后，可安装每两天北京时间 09:00 执行的任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-task.ps1 -Days 2 -At '09:00' -Enable
Get-ScheduledTask -TaskName DouyinViralCollect
Get-ScheduledTaskInfo -TaskName DouyinViralCollect
Disable-ScheduledTask -TaskName DouyinViralCollect
Enable-ScheduledTask -TaskName DouyinViralCollect
```

不带 `-Enable` 时注册为禁用状态。任务首次时间以安装脚本输出为准；同频率重装保留已登记首次时间。电脑须开机、当前 Windows 用户保持登录，关闭开发工具不影响独立 worker。关机、休眠或注销期间不能执行，恢复后补跑。执行时不要用登录脚本占用同一浏览器配置。卸载用 `scripts/uninstall-task.ps1`。

真实执行结果在 `data/scheduler/last-run.json`；`preflight.json` 只是只读预检，不代表已更新文档。完成自己的真实采集与识别、文档副本验证、首条真实定时追加、关闭开发工具后的整轮运行及至少 24 小时观察前，状态保持 `setup_required` 或 `testing`。

## 本地文件、备份与版本管理

- `config.json`：自己的账号、共享文档和开关。
- `data/collect.sqlite3`：作品、状态、错误和写入日志。
- `data/transcripts/`：原识别文本、整理稿及时间戳。
- `data/outbox/`：本地待归档稿和旁路元数据。
- `data/wps-backups/`、`data/wps-write-evidence/`：原格式备份和追加核验证据。
- `models/`、`原始素材/`：本地模型与素材。

这些内容和登录会话均不纳入 Git。公开分享前检查暂存文件、差异和完整提交历史；不要把真实链接写入 README、测试、示例或提交说明。

更新前暂停任务，备份 `config.json` 和整个 `data`，再更新代码、依赖并运行测试与 `doctor`。写入代码改变时副本复验后再恢复任务。不要用 `git clean` 清理本地数据。数据库通过 SQLite 在线备份，恢复前停止 worker 并核对远端未决写入，不能混用旧 WAL。

GitHub 只记录代码版本，不自动同步私人配置、更新文档或部署运行环境。可用 `git status`、`git diff`、`git log --oneline` 查看修改；常规更新使用普通 `git push`。`scripts/github-publish.ps1` 可从当前官方 GitHub CLI 登录账号推断所有者，新仓库默认私有，已有仓库沿用原可见性且检查远程地址，不自动公开。

可选 HTTP 与 n8n 集成见 [N8N_INTEGRATION.md](N8N_INTEGRATION.md)。API 默认关闭，只绑定本机地址；迁移到其他电脑、云端或其他文档布局需重新验证，不复制登录会话给其他人。
