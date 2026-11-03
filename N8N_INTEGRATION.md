# 未来接入 n8n

当前不安装 n8n。业务函数由 Service.run 统一调用，CLI、定时任务、可选 HTTP 共用。平台接口、媒体识别、存储、归档分别在独立模块，未来可增加平台适配器。

需要时安装 `.\.venv\Scripts\python.exe -m pip install -e ".[api]"`。设置 COLLECT_API_TOKEN 至少32字符随机值，再 `collect serve`。只绑定 127.0.0.1:8765；全部路由需要 Authorization: Bearer TOKEN。不要直接暴露公网，迁移时使用受认证反向代理/TLS或私网隧道。API 默认关闭。

HTTP Request 节点：POST /api/monitor/run（整轮）、POST /api/archive/run；GET /api/status、/api/videos、/api/health。接口无请求参数，固定操作；网络请求30秒超时，FFmpeg最长600秒，本地识别时长依素材而定。调用是同步的，n8n超时后不要并发重试，先查任务状态；操作系统锁会拒绝重叠并返回409。长视频可通过独立 CLI worker 运行，未来再加持久任务队列，当前不假设 HTTP 有无限时长。

检查 HTTP 状态及 JSON result 中业务状态，命令 ok=true 不代表已生产上线或 WPS 已连接。n8n 以 Schedule Trigger 每30分钟请求，先停用旧 DouyinViralCollect 任务，避免双触发；先用模拟独立数据目录验证，再切真实配置。n8n在另一台机器时不能通过其 localhost 访问此电脑，需设计受保护的私网连接。云迁移需搬运 SQLite、配置、素材和模型，停止旧 worker 后再启用新 worker；SQLite 保持单机写入。迁移前另行评估云费用。
