import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def marker(account, item):
    return 'collect:' + hashlib.sha256((account + ':' + item).encode()).hexdigest()


def publication_date(value):
    try:
        china = timezone(timedelta(hours=8))
        if isinstance(value, (int, float)) or str(value).isdigit():
            date = datetime.fromtimestamp(float(value), china)
        else:
            text = str(value).strip()
            chinese = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
            date = datetime(*map(int, chinese.groups())) if chinese else datetime.fromisoformat(text.replace('Z', '+00:00'))
            if date.tzinfo:
                date = date.astimezone(china)
        return f'{date.year}年{date.month}月{date.day}日'
    except (ValueError, TypeError, OverflowError, OSError):
        return '日期待获取'


def statistic(value):
    if value is None or isinstance(value, bool):
        return '待获取'
    text = str(value).strip()
    return text if re.fullmatch(r'\d+(?:,\d{3})*(?:\.\d+)?[万亿wWkK]?\+?', text) else '待获取'



def format_paragraphs(body, target_length=200):
    """Reflow ASR fragments; preserve every non-whitespace character."""
    body = re.sub(r'【待核对\d+】', '', body)
    paragraphs, current = [], ''
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        section = re.match(r'^(?:第[一二三四五六七八九十]+(?:点|个|部分)|首先|最后)', line)
        if current and (section or len(current) >= target_length):
            paragraphs.append(current); current = ''
        separator = ' ' if current and current[-1].isascii() and current[-1].isalnum() and line[0].isascii() and line[0].isalnum() else ''
        current += separator + line
    if current:
        paragraphs.append(current)
    return '\n'.join(paragraphs)


def render_entry(row, work):
    header = (f"{publication_date(work.get('published_at'))}，点赞{statistic(work.get('likes_display') if work.get('likes_exact') is False else row.get('likes'))} "
              f"评论{statistic(work.get('comments'))} 收藏{statistic(work.get('favorites'))} "
              f"分享{statistic(work.get('shares'))}；")
    kind = work.get('video_type') or ('图文' if work.get('type') == 'image' else '口播视频')
    body = format_paragraphs(row['body'])
    return header + '\n' + kind + '\n' + work.get('title', '') + '\n' + body


class LocalArchive:
    """Minimal user-facing content; provenance stays in a separate local manifest."""
    def __init__(self, root):
        self.root = Path(root) / 'outbox'
        self.root.mkdir(exist_ok=True)

    def stage(self, row, work, name):
        tag = marker(row['account_id'], row['id'])
        text = render_entry(row, work)
        path = self.root / (tag.split(':')[1] + '.md')
        if not path.exists() or path.read_text(encoding='utf-8') != text:
            if path.exists():
                revisions = self.root / 'revisions'
                revisions.mkdir(exist_ok=True)
                shutil.copy2(path, revisions / (path.stem + '-' + str(time.time_ns()) + '.md'))
            temp = path.with_suffix('.tmp')
            temp.write_text(text, encoding='utf-8'); temp.replace(path)
        metadata = {'marker':tag, 'account_id':row['account_id'], 'work_id':row['id'],
            'account_name':name, 'source_url':work.get('url'), 'checked_at':row.get('checked_at'),
            'recognition_review':work.get('recognition_review'), 'recognition_evidence':work.get('recognition_evidence'),
            'remote_archived':False, 'format_version':2}
        manifest = path.with_suffix('.metadata.json')
        temp = manifest.with_suffix('.tmp')
        temp.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(manifest)
        return str(path)


class WPSAdapter:
    """Implement against the verified document type, not its share URL.

    A concrete adapter must verify permissions, snapshot the original, append
    in a test document and read back full content and marker before enabling.
    Unknown append outcomes must be reconciled by marker, never blindly retried.
    """
    def contains(self, tag):
        raise NotImplementedError('WPS document type and authorized API not verified')

    def append(self, tag, text):
        raise NotImplementedError('production write requires explicit user confirmation')
