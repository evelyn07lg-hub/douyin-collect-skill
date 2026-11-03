---
name: collect
description: 操作和维护抖音作品采集系统，监测自行配置的账号、本地转写口播或图文 OCR，并安全追加到用户自己的金山共享文档；也用于去重和故障排查。
---

在项目根目录使用 `.venv/Scripts/collect.exe`；安装、配置和部署见根目录 README.md。

- 先运行 `status` 和 `doctor`，区分真实监控、导入、模拟、授权及写入状态，不能把已有用户的验证结论推广到新安装。
- 使用本机 `config.json`；从 `config.example.json` 创建后，由用户填入自己的 `public_profiles`、`wps.url` 和准确的 `wps.title`。不在说明、示例、测试或提交中保存真实共享文档链接、目标账号和会话。修改已有配置前备份；不覆盖正在使用的配置。
- 浏览器模式可用另一个登录账号查看目标账号公开主页。`public_profiles` 的 `sec_uid` 不是官方 OAuth `open_id`；昵称与主页须实际核对后再设 `name_verified`，不按搜索结果或链接顺序猜测。目标账号数量由配置决定。
- 登录使用 `scripts/browser-probe.ps1` 和 `scripts/wps-login.ps1`，用户自行完成验证；不读取或分享 `data/browser-profile`，不向用户索要密码或 Token。验证码、限流和访问限制返回 `browser_action_required`，不绕过。
- `check` 监测；`browser-check` 有预算扫描；`backfill`/`browser-backfill` 扫描历史，但 partial/stalled 不是完整历史。详情须核对作者和作品 ID。官方路径需要真实开放平台权限及账号授权。
- `process --retry` 恢复失败识别；素材通过作品 ID 和本地 `media` 显式映射，不靠文件名猜测。原文件优先；仅可保存正常授权的播放器音轨，并核验完整性与时长。缺少合法素材保持 `waiting_media`，不编造逐字稿。不生成平台签名，不绕过 DRM 或拒绝访问。
- `browser-export` 仅输出发布描述，不含口播或图内文字，也不设置 archived。点赞必须严格大于配置阈值，默认 500；缩写保留待核验，不假设精确值。
- `archive` 生成本地待归档文件；启用 WPS 后会执行真实追加。`run` 是完整一轮；`videos` 查看处理状态；`logs` 查错误；`backup` 在线备份数据库。`ok=true` 或本地 outbox 不等于远端写入成功，不能手改 archived 冒充成功。
- 正式写入前核验用户自己的链接、准确标题、文档类型及编辑权限，备份原格式文件，在独立副本验证各账号分区追加和全文、格式保护，并取得明确确认。不能复用他人的本地证明。“可评论”不等于可编辑，截图不等于原格式备份；写入代码或模板变化须重新验证。
- 已有文字、格式、统计全部保留，仅向对应账号分区末尾追加未收录达标稿。按已有收录日期建立增量基线，复查已观察后跨阈值的旧稿。疑似重复为 `duplicate_review`，未知写入为 `uncertain`；先核验远端，不盲目重试。
- 正文格式默认：首行“发布年月日，点赞x 评论x 收藏x 分享x；”，换行依次写类型、标题、完整正文；自然段之间只空一行，合并 ASR 碎行，不删改原话。缺失统计写“待获取”，不填假 0。账号、来源、识别说明和去重证据保存在旁路元数据中，不加到文档正文。用户可另行要求格式，改变写入模板后需复验。
- Skill 不提供后台进程。用户选择定时时用 Windows 任务计划程序；默认建议每两天北京时间 09:00，实际频率和启用状态以用户配置为准，不声称新安装已注册任务。`data/scheduler/last-run.json` 才是真实整轮结果，preflight 不是更新成功。
- 新环境未完成所选采集路径、真实素材、WPS 备份和副本验证、真实定时追加及至少 24 小时观察前，保持 `setup_required`/`testing`。不调用未授权的付费服务。未来 HTTP/n8n 迁移见 N8N_INTEGRATION.md。
