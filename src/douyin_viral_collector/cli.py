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
    s=sub.add_parser('setup',help='首次配置目标账号和点赞门槛，默认生成本地Word')
    s.add_argument('--profile',action='append',dest='profiles');s.add_argument('--min-likes',type=int);s.add_argument('--strict',action='store_true');s.add_argument('--output-dir')
    binding=sub.add_parser('bind-media',help='为待处理作品关联自己的原视频')
    binding.add_argument('--work-id',required=True);binding.add_argument('--file',required=True)
    sub.add_parser('login',help='打开浏览器，登录并核对账号名称')
    sub.add_parser('organize',help='一键采集并生成Word；需要先完成setup和首次登录')
    s=sub.add_parser('export-word',help='生成Word文稿；无需金山文档')
    s.add_argument('--input',dest='input_file');s.add_argument('--output');s.add_argument('--no-cover',action='store_true')
    args = vars(p.parse_args())
    command, config = args.pop('command'), args.pop('config')
    try:
        if command == 'setup':
            from .onboarding import setup
            output={'ok':True,'result':setup(config,**args)}
        elif command == 'bind-media':
            from .media_binding import bind_media
            from .storage import lock
            service=Service(config)
            try:
                with lock(service.root/'collect.lock'):output={'ok':True,'result':bind_media(service,**args)}
            finally:service.store.db.close()
        elif command == 'login':
            from .onboarding import verify_profiles
            output={'ok':True,'result':verify_profiles(config,interactive=True)}
        elif command == 'organize':
            from .onboarding import verify_profiles
            verify_profiles(config)
            service=Service(config)
            try:output={'ok':True,'result':service.run('run')}
            finally:service.store.db.close()
        elif command == 'export-word':
            from .word_export import export_word
            from pathlib import Path
            records=json.loads(Path(args['input_file']).read_text(encoding='utf-8-sig')) if args.get('input_file') else None
            service=Service(config)
            try:output={'ok':True,'result':export_word(service,output=args.get('output'),records=records,cover=not args['no_cover'])}
            finally:service.store.db.close()
        elif command == 'test':
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
