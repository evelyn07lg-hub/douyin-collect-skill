"""Standard-library controller used by the independent desktop window."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path


class DesktopRunner:
    def __init__(self, root, emit=lambda event: None):
        self.root = Path(root).resolve()
        self.emit = emit
        self.python = self.root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.cancelled = threading.Event()
        self.process = None

    def _command(self, args, login=False):
        if self.cancelled.is_set():
            raise RuntimeError('操作已取消')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
        env['PYTHONPATH']=str(self.root/'src')+os.pathsep+env.get('PYTHONPATH','')
        command = [str(self.python), '-u', *map(str, args)]
        self.process = subprocess.Popen(command, cwd=self.root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if login:
            self.emit({'kind': 'login_required'})
        answer = None
        try:
            for line in self.process.stdout:
                self.emit({'kind': 'log', 'text': line.rstrip()})
                try:
                    item = json.loads(line)
                    if isinstance(item, dict) and 'ok' in item:
                        answer = item
                except ValueError:
                    pass
            code = self.process.wait()
            if self.cancelled.is_set():
                raise RuntimeError('操作已取消')
            if code or (answer is not None and not answer['ok']):
                raise RuntimeError((answer or {}).get('error') or '当前步骤未完成，请查看运行记录。')
            return (answer or {}).get('result', {})
        finally:
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None

    def continue_login(self):
        process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write('\n')
            process.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def cancel(self):
        self.cancelled.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def prepare(self):
        from .environment_setup import choose_runtime,requirements
        self.emit({'kind':'stage','text':'检测已有依赖和可复用的 Python 环境'})
        needed=requirements(self.config());self.python,missing=choose_runtime(self.root,sys.executable,needed)
        if not missing:
            self.emit({'kind':'stage','text':'依赖已就绪，跳过安装'})
            return
        if not self.python.is_file():
            self.emit({'kind':'stage','text':'创建项目专用环境'})
            subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(self.root/'.venv')],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        from .environment_setup import probe
        detected=probe(self.python,needed)
        if detected is not None:missing=detected['missing']
        if not missing:
            self.emit({'kind':'stage','text':'依赖已就绪，跳过安装'})
            return
        self.emit({'kind':'stage','text':f'补齐 {len(missing)} 个缺失组件，详情见运行记录'})
        self.emit({'kind':'log','text':'缺失组件：'+', '.join(missing)})
        self._command(['-m','pip','install','--prefer-binary','--disable-pip-version-check',*missing])
        from .environment_setup import probe
        checked=probe(self.python,needed)
        if checked is None or checked['missing']:raise RuntimeError('依赖检查未通过，请查看运行记录。')

    @staticmethod
    def validate(profiles, minimum):
        from .share_links import extract_links
        urls = extract_links(profiles)
        if isinstance(minimum, bool) or not str(minimum).isdigit():
            raise ValueError('点赞门槛需要填写非负整数。')
        return list(dict.fromkeys(urls)), int(minimum)

    def config(self):
        path = self.root / 'config.json'
        return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}

    def start(self, profiles, minimum, strict=False, output_dir='exports', model='small', login_only=False, browser='edge'):
        urls, minimum = self.validate(profiles, minimum)
        if model not in ('small', 'large-v3-turbo'):
            raise ValueError('不支持的本地识别模型。')
        self.cancelled.clear()
        self.prepare()
        if browser not in ('edge','chrome'):raise ValueError('请选择 Edge 或 Chrome')
        selected=self.config()
        if not selected:
            selected=json.loads((self.root/'config.example.json').read_text(encoding='utf-8-sig'))
        selected['browser']=browser
        if selected:(self.root/'config.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
        self.emit({'kind': 'stage', 'text': '保存账号和整理条件'})
        args = ['-m', 'douyin_viral_collector.cli', 'setup', '--min-likes', minimum, '--output-dir', output_dir]
        for url in urls:
            args += ['--profile', url]
        if strict:
            args.append('--strict')
        self._command(args)
        config = self.config()
        from .environment_setup import existing_model
        reused=existing_model(self.root,sys.executable,model)
        config['model'] = str(reused) if reused else 'models/faster-whisper-' + model
        if reused:self.emit({'kind':'stage','text':'已找到本机识别模型，跳过下载'})
        config.setdefault('wps', {}).setdefault('enabled', False)
        (self.root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if not login_only and not (self.root / config['model'] / 'model.bin').is_file():
            self.emit({'kind': 'stage', 'text': '首次下载识别模型，此步骤可能需要较长时间'})
            self._command(['scripts/download-model.py', '--model', model])
        known = config.get('public_profiles', [])
        if login_only or not known or not all(p.get('name_verified') for p in known):
            self.emit({'kind': 'stage', 'text': '请在浏览器完成抖音登录，再点击“登录完成，继续”'})
            self._command(['-m', 'douyin_viral_collector.cli', 'login'], login=True)
        if login_only:
            self.emit({'kind': 'stage', 'text': '登录已完成，可以开始整理。'})
            return {}
        self.emit({'kind': 'stage', 'text': '正在采集和识别，较长视频需要更多时间'})
        result = self._command(['-m', 'douyin_viral_collector.cli', 'organize'])
        self.emit({'kind': 'export', **result.get('word', {})})
        return result

    def export(self):
        self.cancelled.clear()
        if not (self.root / 'config.json').is_file():
            raise ValueError('请先填写账号并开始首次整理。')
        self.prepare()
        result = self._command(['-m', 'douyin_viral_collector.cli', 'export-word'])
        self.emit({'kind': 'export', **result})
        return result

    def bind_and_process(self, work_id, filename):
        self.cancelled.clear()
        self.prepare()
        self._command(['-m', 'douyin_viral_collector.cli', 'bind-media', '--work-id', work_id, '--file', filename])
        self.emit({'kind': 'stage', 'text': '正在识别关联的原视频'})
        self._command(['-m', 'douyin_viral_collector.cli', 'process', '--retry'])
        return self.export()

    def items(self):
        config = self.config()
        database = self.root / config.get('data_dir', 'data') / 'collect.sqlite3'
        if not database.is_file():
            return []
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute('SELECT id,payload,likes,status FROM works ORDER BY checked_at DESC').fetchall()
        finally:
            connection.close()
        items = []
        threshold = config.get('minimum_likes', config.get('threshold', 500) + 1)
        for row in rows:
            if row['likes'] < threshold:
                continue
            item = json.loads(row['payload'])
            items.append({'id': row['id'], 'account': item.get('account_name', ''),
                'date': item.get('published_at', ''), 'title': item.get('title', ''),
                'likes': row['likes'], 'status': row['status']})
        return items
