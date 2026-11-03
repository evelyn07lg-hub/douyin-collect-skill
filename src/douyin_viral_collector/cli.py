import argparse
import json
import sys
from .service import Service


def main():
    p = argparse.ArgumentParser(description='Collect: authorized Douyin collection, JSON output')
    p.add_argument('--config', default='config.json', help='persistent JSON configuration')
    sub = p.add_subparsers(dest='command', required=True)
    for cmd, help_text in {'check': '监测新作品并复查旧作品', 'backfill': '完整历史扫描',
        'process': '本地识别，--retry 重试失败', 'archive': '保存完整 Markdown 待归档文件',
        'status': '查看状态', 'doctor': '检查环境与授权', 'run': '执行完整一轮',
        'backup': '在线备份 SQLite', 'logs': '最近错误日志', 'videos': '作品列表',
        'browser-check': '浏览器采集新作品并核验详情', 'browser-backfill': '浏览器历史滚动扫描（有限预算）',
        'browser-import': '将已保存主页证据加入待核验队列', 'browser-export': '导出已核验发布文案（不含口播和图片OCR）',
        'test': '执行自动化测试', 'serve': '启动可选本地认证 API', 'import': '导入 JSON/CSV'}.items():
        s = sub.add_parser(cmd, help=help_text, description=help_text)
        if cmd in ('browser-check', 'browser-backfill'):
            s.add_argument('--max-scrolls', type=int, default=4 if cmd == 'browser-check' else 30, help='每个主页最多滚动轮数，0至200')
            s.add_argument('--max-details', type=int, default=6, help='本轮最多核验详情数，0至100')
        if cmd == 'process': s.add_argument('--retry', action='store_true')
        if cmd == 'import': s.add_argument('file')
    args = vars(p.parse_args())
    command, config = args.pop('command'), args.pop('config')
    try:
        if command == 'test':
            import unittest
            from pathlib import Path
            suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parents[2] / 'tests'))
            result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
            output = {'ok': result.wasSuccessful(), 'tests': result.testsRun}
        elif command == 'serve':
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(config), host='127.0.0.1', port=8765)
            return
        else:
            service = Service(config)
            try:
                output = {'ok': True, 'result': service.run(command, **args)}
            finally:
                service.store.db.close()
    except Exception as exc:
        # Avoid raw HTTP exceptions that may include OAuth query secrets.
        output = {'ok': False, 'error': str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__}
    print(json.dumps(output, ensure_ascii=False))
    if not output['ok']: raise SystemExit(1)


if __name__ == '__main__':
    main()
