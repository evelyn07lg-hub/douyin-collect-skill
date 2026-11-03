---
name: collect
description: 操作和维护抖音爆款采集系统，执行账号作品监测、本地口播转写和图文 OCR、去重、WPS 待归档及故障排查。
---

在项目根目录使用 `.venv/Scripts/collect.exe`；部署与配置见根目录 README.md。

- 先运行 `status` 和 `doctor`，明确真实监控、导入、模拟及授权状态。
- `check` 监测；`backfill` 补录完整历史；`process --retry` 恢复失败识别；`archive` 生成待归档 Markdown；`run` 执行一轮；`videos` 查看未完成作品；`logs` 看错误；`backup` 备份数据库。
- 当前用户选择使用另一个账号登录浏览器，查看三个目标账号的公开主页，不要求三个目标分别 OAuth 授权。public_profiles 保存主页 sec_uid，不能将其当作官方 open_id。昵称映射须通过实际页面核对，不能按链接顺序猜测。
- 浏览器登录使用 scripts/browser-probe.ps1。采集用 `browser-check`，历史扫描用 `browser-backfill --max-scrolls 30 --max-details 6`。每轮有预算，partial/stalled 不代表完整历史。`browser-import` 只导入发现线索，必须通过真实主页封面作者匹配后才能进详情队列；详情还要核验作者主页与作品 ID。
- `browser-export` 将已核验、精确点赞大于500的发布文案保存到 data/publishing-copy；这是发布描述，不含口播或图片内文字，不更新 archived。缩写点赞保留待核验，不按精确数字入库。
- 登录态在 data/browser-profile，不读取或分享会话文件。验证码、登录或访问限制会返回 browser_action_required，交给用户处理，不绕过。`browser_last_run` 可在 status 查询。
- 修改配置前备份 config.json；官方模式仍使用授权 open_id。素材使用导入记录的 media 显式映射；时间/文件名模糊匹配应由用户核对。
- 本地 outbox 不等于远端成功，禁止把 ready_to_archive 改成 archived 来表示本地保存。WPS 浏览器适配器已在独立副本通过三账号追加与原格式保护，生产开关按已验证证明启用，但状态仍testing。
- 正式 WPS 自动写入必须先验证文档类型、权限、备份、测试文档追加与完整性，再取得用户明确确认。未知写入结果先核验唯一标识，不能盲目重试。
- 不读取或输出 Token；不调用付费服务；缺少素材保持 waiting_media，不编造逐字稿。
- Skill 不负责后台调度，任务由 Windows 计划程序执行。未来 n8n 迁移见 N8N_INTEGRATION.md。
- 未完成所选采集路径的真实验证、真实素材识别、WPS 测试和确认、关闭 Codex 后定时执行及连续 24 小时观察，保持 setup_required/testing。

- 用户最终指定的归档正文仅为：第一行“发布年月日，点赞x 评论x 收藏x 分享x；”，其后换行依次写类型、标题、完整正文。不要加入账号、来源链接、采集时间、识别状态、校对说明或可见归档标识。去重标识和校对证据保存在独立元数据；正式远端写入仍需有独立可靠的幂等校验，不得为了省字段放弃去重。缺失统计写待获取，不能填0；“万”等缩写原样保留。

- 正文使用连贯的自然段，合并ASR逐句碎行；每段结束后只空一行，不要每句话都换行或空行。仅调整空白，不删减或改写原话。

- 金山登录检查入口为 scripts/wps-login.ps1，仅由用户自行登录后只读检查。status.wps_readiness记录状态；“可评论”访客页面不能当作已验证编辑权限。页面截图/可见文字不等于原格式全量备份。

- 最新要求：正式文档已有文字、格式、统计数字全部保持原样，仅向对应账号分区追加尚未收录的新增过500赞稿件。用户指定每两天更新一次，默认北京时间09:00。任务已在副本验证后启用，首次2026年11月4日09:00，此后每两天执行；真实新增稿及24小时观察未完成前保持testing，不能宣称production_ready。样本作品example-work-id已在原文档日常账号分区发现，不重复追加或替换。

- 当前增量以原文档各账号最近收录日期为准，避免漏掉尚未收录的最新达标稿；基线中已观察低赞的旧稿后来跨500也可处理。疑似重复为duplicate_review，未知写入为uncertain，不自动复写。原文及旧统计数字始终不改。
- 正常授权播放器音轨可自动保存，拒绝访问/不完整/无法核对时长则waiting_media；不能生成签名、绕过DRM、验证码或访问限制。用户原文件优先。定时真实执行见data/scheduler/last-run.json；preflight不是文档更新成功。
