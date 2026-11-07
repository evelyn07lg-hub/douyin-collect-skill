"""Explicitly bind a user's original video to a pending, verified work."""
import json
from pathlib import Path


def inspect_media(path):
    import av
    with av.open(str(path)) as container:
        return {'audio': bool(container.streams.audio), 'video': bool(container.streams.video)}


def bind_media(service, work_id, file):
    path = Path(file).resolve()
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('原视频不存在或为空。')
    rows = service.store.rows('SELECT * FROM works WHERE id=?', (str(work_id),))
    if len(rows) != 1:
        raise ValueError('请先在作品列表中选择唯一、已采集的作品。')
    row = rows[0]
    if row['status'] in ('archived', 'already_present', 'exported_local', 'ready_to_archive', 'duplicate_review', 'uncertain'):
        raise ValueError('这篇作品已有稿件或需要单独核对，不自动覆盖现有校订。')
    work = json.loads(row['payload'])
    if work.get('type', 'video') != 'video':
        raise ValueError('此入口用于口播视频；图文请使用图片素材整理流程。')
    tracks = inspect_media(path)
    if not tracks['audio']:
        raise ValueError('选择的文件没有音轨；不能据此认定作品没有口播。')
    work.update(media=[str(path)], media_mapping_source='user_selected_work_id')
    if tracks['video']:
        work['subtitle_media'] = [str(path)]
    service.store.execute("UPDATE works SET payload=?,status='discovered',error=NULL WHERE account_id=? AND id=?",
        (json.dumps(work, ensure_ascii=False), row['account_id'], row['id']))
    return {'id': row['id'], 'mapped': True, 'has_video_picture': tracks['video'], 'mapping_source': 'user_selected_work_id'}
