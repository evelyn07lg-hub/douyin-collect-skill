"""Public, logged-in DOM collector. No private endpoints, signing or CAPTCHA bypass."""
import json
from .browser_choice import browser_options
from .progress import progress
import re
import time
import sys
from pathlib import Path
from urllib.parse import urlsplit
from .service import now

CARD_SELECTOR = 'a:has(.author-card-user-video-like)'
PUBLIC_PREFIX = 'douyin-public:'


class BrowserBlocked(RuntimeError):
    pass


def author_cover_matches(alt,name):
    return str(alt).startswith(name+'：') or bool(re.fullmatch(re.escape(name)+r'于\d{8}发布的作品',str(alt)))


def exact_count(value):
    value = str(value).strip()
    return int(value.replace(',', '')) if re.fullmatch(r'\d+|\d{1,3}(?:,\d{3})+', value) else None


def count_interval(value):
    from decimal import Decimal,ROUND_FLOOR
    text=str(value).strip();exact=exact_count(text)
    if exact is not None:return exact,exact
    match=re.fullmatch(r'(\d+(?:\.\d+)?)(万|亿|[wWkK])',text)
    if match:
        number=Decimal(match[1]);unit=Decimal(100000000 if match[2]=='亿' else 1000 if match[2].lower()=='k' else 10000)
        step=Decimal(10)**number.as_tuple().exponent
        lower=max(0,int(((number-step/2)*unit).to_integral_value(rounding=ROUND_FLOOR)))
        upper=int(((number+step)*unit).to_integral_value(rounding=ROUND_FLOOR))-1
        return lower,upper
    match=re.fullmatch(r'(\d+)\+',text)
    return (int(match[1]),None) if match else None


def parse_card(link):
    match = re.fullmatch(r'https://www\.douyin\.com/(video|note)/(\d+)/?(?:\?.*)?', link.get('url', ''))
    if not match:
        return None
    lines = link.get('text', '').strip().splitlines()
    while lines and lines[0].strip() in ('置顶', ''):
        lines.pop(0)
    display = link.get('likes_display', lines.pop(0).strip() if lines else '')
    return {'id': match[2], 'type': 'image' if match[1] == 'note' else 'video',
        'url': f'https://www.douyin.com/{match[1]}/{match[2]}', 'likes_display': display,
        'likes_exact_display': exact_count(display), 'description': link.get('description', '\n'.join(lines).strip()),
        'transcript': None, 'needs_detail_verification': True}


def validate_detail(card, detail, allow_homepage_coauthored=False, threshold=None):
    """Reject wrong author/work, ambiguous counts, changed layouts and truncated copy."""
    expected = 'https://www.douyin.com/user/' + card['account_id'].removeprefix(PUBLIC_PREFIX)
    if detail.get('url', '').split('?')[0].rstrip('/') != card['url']:
        raise ValueError('detail_url_mismatch')
    authors={u.split('?')[0].rstrip('/') for u in detail.get('author_urls', [])}
    coauthored=bool(expected not in authors and authors and allow_homepage_coauthored and card.get('profile_card_verified') and card.get('profile_url')==expected and str(detail.get('work_id'))==card['id'])
    if expected not in authors and not coauthored:
        raise ValueError('detail_author_mismatch')
    if detail.get('work_id') and str(detail['work_id']) != card['id']:
        raise ValueError('detail_work_id_mismatch')
    count = exact_count(detail.get('likes_display', ''))
    interval=count_interval(detail.get('likes_display',''));is_exact=count is not None
    if count is None:
        if threshold is None or interval is None or not (interval[0]>threshold or (interval[1] is not None and interval[1]<=threshold)):
            raise ValueError('likes_require_review: 点赞缩写范围与门槛重叠，需要精确核验')
        count=interval[0]
    text = detail.get('description', '')
    if (not text.strip() and not detail.get('description_empty_confirmed')) or not detail.get('published_at') or detail.get('expand_remaining'):
        raise ValueError('detail_layout_or_description_incomplete')
    return dict(card, likes=count,likes_exact=is_exact,likes_interval=interval, description=text,homepage_coauthored=coauthored,detail_author_urls=list(authors), title=text.splitlines()[0] if text.strip() else '未填写发布文案',
        published_at=detail['published_at'], detail_verified=True,
        likes_display=detail['likes_display'], needs_detail_verification=False,
        comments=detail.get('comments_display'), favorites=detail.get('favorites_display'),
        shares=detail.get('shares_display'), content_kind='publishing_description', description_complete=True)


def confirmed_other_author(card,evidence):
    expected='https://www.douyin.com/user/'+card['account_id'].removeprefix(PUBLIC_PREFIX)
    authors={url.split('?')[0].rstrip('/') for url in evidence.get('author_urls',[])}
    return bool(authors and expected not in authors and str(evidence.get('work_id'))==card['id'] and evidence.get('url','').split('?')[0].rstrip('/')==card['url'])


def save_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


class BrowserCollector:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.root = service.root
        self.config = service.config
        self.store.execute('''CREATE TABLE IF NOT EXISTS browser_candidates(
            account_id TEXT, id TEXT, payload TEXT NOT NULL, observed_at TEXT,
            detail_checked TEXT, detail_status TEXT DEFAULT 'pending', error TEXT,
            PRIMARY KEY(account_id,id))''')

    def remember(self, card, profile, profile_card_verified=False):
        card = dict(card, account_id=PUBLIC_PREFIX + profile['sec_uid'], account_name=profile['name'],profile_url='https://www.douyin.com/user/'+profile['sec_uid'])
        prior = self.store.rows('SELECT payload FROM browser_candidates WHERE account_id=? AND id=?', (card['account_id'], card['id']))
        card['profile_card_verified'] = profile_card_verified or bool(prior and json.loads(prior[0]['payload']).get('profile_card_verified'))
        self.store.execute('''INSERT INTO browser_candidates(account_id,id,payload,observed_at)
            VALUES(?,?,?,?) ON CONFLICT(account_id,id) DO UPDATE SET payload=excluded.payload,observed_at=excluded.observed_at''',
            (card['account_id'], card['id'], json.dumps(card, ensure_ascii=False), now()))
        return card

    def import_evidence(self):
        dirs = sorted(p for p in (self.root / 'browser-probe').iterdir() if p.is_dir() and list(p.glob('profile-*.json')))
        if not dirs:
            raise ValueError('No saved public profile evidence')
        profiles = {p['sec_uid']: p for p in self.config.get('public_profiles', []) if p.get('name_verified')}
        count = 0
        for path in sorted(dirs[-1].glob('profile-*.json')):
            v = json.loads(path.read_text(encoding='utf-8'))
            profile = profiles.get(v['sec_uid'])
            if not profile or v.get('actual_url', '').split('?')[0].rstrip('/') != 'https://www.douyin.com/user/' + v['sec_uid']:
                continue
            if v['title'] != profile['name'] + '的抖音 - 抖音':
                continue
            for link in v.get('links', []):
                card = parse_card(link)
                if card:
                    self.remember(card, profile); count += 1
        return {'remembered': count, 'source': 'saved_evidence', 'historical_complete': False}

    def guard(self, page):
        # Visible login/verification prompts only. Do not inspect cookies/storage or page scripts.
        for phrase in ('请完成下方验证', '拖动滑块完成拼图', '请进行安全验证', '访问过于频繁', '扫码登录', '账号密码登录'):
            prompt = page.get_by_text(phrase, exact=True)
            if any(prompt.nth(i).is_visible() for i in range(min(prompt.count(), 4))):
                raise BrowserBlocked('browser_action_required: login, verification or rate limit')

    def open(self, page, url):
        from playwright.sync_api import Error
        navigation_failed = False
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
        except Error:
            navigation_failed = True
        page.wait_for_timeout(1800)
        self.guard(page)
        if page.url.split('?')[0].rstrip('/') != url:
            raise BrowserBlocked('browser_action_required: unexpected redirect')
        if navigation_failed:
            self.store.event('browser_navigation', 'navigation interrupted; target URL reached, DOM still requires validation')
        # Prevent automatic playback or advancing to a different work.
        page.locator('video').evaluate_all('(ns)=>ns.forEach(n=>n.pause())')

    def scan_profile(self, page, profile, historical, max_scrolls):
        url = 'https://www.douyin.com/user/' + profile['sec_uid']
        self.open(page, url)
        page.wait_for_function('document.querySelectorAll("a .author-card-user-video-like").length>0', timeout=20000)
        if page.title() != profile['name'] + '的抖音 - 抖音':
            raise BrowserBlocked('profile_identity_changed: review nickname')
        seen, stale, total = set(), 0, None
        listing_positions = {}
        # Read only the count match from body; do not persist personal UI or message panels.
        total_match = re.search(r'(?:^|\n)作品\s*\n(\d+)(?:\n|$)', page.locator('body').inner_text())
        if total_match:
            total = int(total_match[1])
        reason = 'scroll_budget_reached'
        known_rounds = 0
        for step in range(max_scrolls + 1):
            self.guard(page)
            links = page.locator(CARD_SELECTOR).evaluate_all('''ns=>ns.map(n=>({url:n.href,
                likes_display:n.querySelector('.author-card-user-video-like')?.innerText,
                description:n.querySelector('p')?.textContent || '',
                author_alt:n.querySelector('img')?.alt || '', pinned:Boolean(n.querySelector('.user-video-tag')?.innerText.includes('置顶'))}))''')
            fresh, unknown = 0, 0
            for link in links:
                # Author-specific cover text excludes recommendation cards.
                if not author_cover_matches(link['author_alt'],profile['name']):
                    continue
                card = parse_card(link)
                if not card:
                    continue
                card['listing_order'] = listing_positions.setdefault(card['id'], len(listing_positions))
                card['is_pinned'] = link.get('pinned', False)
                key = (PUBLIC_PREFIX + profile['sec_uid'], card['id'])
                known = self.store.db.execute('SELECT 1 FROM browser_candidates WHERE account_id=? AND id=?', key).fetchone()
                if not known: unknown += 1
                if card['id'] not in seen: fresh += 1
                seen.add(card['id']); self.remember(card, profile, profile_card_verified=True)
            stale = stale + 1 if not fresh else 0
            known_rounds = known_rounds + 1 if not unknown else 0
            if total is not None and len(seen) >= total:
                reason = 'displayed_count_reached'; break
            if not historical and step >= 2 and known_rounds >= 2:
                reason = 'known_window_reached'; break
            if stale >= 3:
                reason = 'stalled_requires_review'; break
            if step < max_scrolls:
                cards = page.locator(CARD_SELECTOR)
                if cards.count(): cards.last.scroll_into_view_if_needed(timeout=10000)
                page.mouse.wheel(0, 1100)
                page.wait_for_timeout(1200)
        result = {'name': profile['name'], 'observed': len(seen), 'displayed_total': total,
            'stop_reason': reason, 'historical_complete': reason == 'displayed_count_reached'}
        self.store.set('browser_scan:' + profile['sec_uid'], result)
        return result

    def detail(self, page, card):
        from .media_sources import collect_response, save_visible_audio, save_visible_media
        sources = {}
        listener = lambda response: collect_response(response, sources)
        page.on('response', listener)
        def finished(request):
            if request.url in sources:sources[request.url]['_finished']=True
        page.on('requestfinished',finished)
        self.open(page, card['url'])
        author = page.locator('[data-e2e="user-info"]').first.locator('a[href*="/user/"]')
        author.first.wait_for(state='attached', timeout=15000)
        authors = author.evaluate_all('(ns)=>ns.map(n=>n.href)')
        if card['type'] == 'video':
            scope = page.locator('[data-e2e="detail-video-info"]').first
            scope.wait_for(state='visible', timeout=15000)
            expand = scope.get_by_role('button', name='展开', exact=True)
            if expand.count() and expand.first.is_visible(): expand.first.click(timeout=5000)
            description = scope.locator('h1').inner_text()
            counts = scope.locator('span.hIpNkUXt')
            display = counts.first.inner_text() if counts.count() >= 3 else ''
            comments = counts.nth(1).inner_text() if counts.count() >= 3 else None
            favorites = counts.nth(2).inner_text() if counts.count() >= 3 else None
            share_node = scope.locator('[data-e2e="video-share-icon-container"] span.sB3y0d3B')
            shares = share_node.first.inner_text() if share_node.count() else None
            published = scope.locator('[data-e2e="detail-video-publish-time"]').inner_text()
            work_id = scope.get_attribute('data-e2e-aweme-id')
        else:
            player = page.locator('main[data-e2e="note-detail"] [data-e2e="player-container"]').first
            player.wait_for(state='visible', timeout=15000)
            scope = page.locator('[data-e2e="user-info"]').first.locator('..')
            expand = scope.get_by_role('button', name='展开', exact=True)
            if expand.count() and expand.first.is_visible(): expand.first.click(timeout=5000)
            description = scope.locator('.Bfj9rfeR').inner_text()
            display = player.locator('[data-e2e="video-player-digg"]').first.inner_text()
            def stat(selector):
                node = player.locator(selector).first
                return node.inner_text() if node.count() else None
            comments = stat('[data-e2e="feed-comment-icon"]')
            favorites = stat('[data-e2e="video-player-collect"]')
            shares = stat('[data-e2e="video-player-share"]')
            published = scope.locator('.mbFdUIBS').inner_text()
            work_id = None
        remaining = scope.get_by_role('button', name='展开', exact=True)
        evidence = {'url': page.url, 'author_urls': authors, 'work_id': work_id,
            'likes_display': display.strip(), 'comments_display': comments,
            'favorites_display': favorites, 'shares_display': shares, 'description': description,
            'published_at': published.removeprefix('发布时间：').strip(),
            'expand_remaining': any(remaining.nth(i).is_visible() for i in range(remaining.count()))}
        evidence['description_empty_confirmed']=bool(card['type']=='video' and not description.strip() and str(work_id)==card['id'] and scope.locator('h1').count()==1)
        save_json(self.root/'browser-detail-attempts'/(card['id']+'.json'),evidence)
        work = validate_detail(card,evidence,allow_homepage_coauthored=self.config.get('collection',{}).get('include_homepage_coauthored',True),threshold=self.config['threshold'])
        if work['type']=='image' and self.config.get('collection',{}).get('image_mode')=='published_copy':
            work.update(content_mode='published_copy',image_copy_requested=True,video_type='图文文案')
        if work['id'] in {str(v) for v in self.config.get('caption_only_work_ids', [])}:
            work.update(content_mode='published_copy', no_spoken_confirmed=True, video_type='视频文案')
        from .append_policy import eligible
        decision, reason = eligible(work, self.store, self.config)
        work['eligible_for_append'], work['eligibility_reason'] = decision, reason
        if decision and work['type'] == 'video' and work.get('content_mode') != 'published_copy' and self.config.get('media_sources', {}).get('authorized_player_download'):
            existing = self.store.rows('SELECT payload FROM works WHERE account_id=? AND id=?', (work['account_id'],work['id']))
            prior_media = json.loads(existing[0]['payload']).get('media', []) if existing else []
            if isinstance(prior_media, str):prior_media = [prior_media]
            if prior_media:work['media'] = prior_media
            if existing:
                prior_subtitles=json.loads(existing[0]['payload']).get('subtitle_media',[])
                if prior_subtitles:work['subtitle_media']=prior_subtitles
                prior_capture=json.loads(existing[0]['payload']).get('subtitle_capture')
                if prior_capture:work['subtitle_capture']=prior_capture
            captions_enabled=self.config.get('proofreading',{}).get('video_subtitles',{}).get('enabled',False)
            from .subtitles import subtitle_video,browser_caption_evidence
            complete_audio=prior_media and all((Path(p) if Path(p).is_absolute() else self.service.path.parent / p).is_file() for p in prior_media)
            complete_video=(subtitle_video(work,self.root) is not None or browser_caption_evidence(work,self.root) is not None) if captions_enabled else True
            if not (complete_audio and complete_video):
                durations = page.locator('video').evaluate_all('(ns)=>ns.map(n=>n.duration).filter(n=>Number.isFinite(n)&&n>1)')
                if captions_enabled:
                    source=save_visible_media(page.context,work,sources,durations,self.root,
                        allow_network=not self.config.get('media_sources',{}).get('browser_buffer_only',False))
                else:source=save_visible_audio(page.context,work,sources,durations,self.root)
                work['media_source_status'] = source
                if source.get('status') == 'saved' and source.get('path'):work['media'] = [source['path']]
                if source.get('subtitle_path'):work['subtitle_media']=[source['subtitle_path']]
            if self.config.get('media_sources',{}).get('browser_capture_when_needed',True):
                from .media import media_paths
                try:
                    if not media_paths(work,self.root):
                        from .player_audio import record_visible_audio
                        progress('正在读取当前视频的完整音轨，请等待播放完成')
                        captured=record_visible_audio(page,work,self.root)
                        work['media']=[captured['path']];work['media_mapping_source']=captured['source']
                        self.open(page,card['url'])
                    if captions_enabled and subtitle_video(work,self.root) is None and browser_caption_evidence(work,self.root) is None:
                        from .player_captions import capture_player_subtitles
                        captured=capture_player_subtitles(page,work,self.root,self.config['proofreading']['video_subtitles'],lambda v:progress(f"正在核对字幕：{v.get('frames',0)}/{v.get('total',0)} 帧"))
                        if captured.get('capture_complete'):work['subtitle_capture']=captured['path']
                except Exception as capture_error:
                    work['capture_issue']=str(capture_error)[:200]

        page.remove_listener('response', listener)
        page.remove_listener('requestfinished',finished)
        save_json(self.root / 'browser-details' / (card['id'] + '.json'), dict(evidence, checked_at=now()))
        return work

    def pending(self, limit):
        # Oldest checked first; rotate errors/reviews, no starvation of newly found works.
        rows = self.store.rows("""SELECT c.*,w.status AS work_status,w.likes AS previous_likes FROM browser_candidates c LEFT JOIN works w
            ON c.account_id=w.account_id AND c.id=w.id
            WHERE w.status IS NULL OR w.status NOT IN ('archived','already_present','duplicate_review')""")
        rows = [r for r in rows if json.loads(r['payload']).get('profile_card_verified')]
        if self.config.get('append_policy'):
            from .append_policy import ensure_baseline
            ensure_baseline(self.store)
            ignored = {(r['account_id'],r['id']) for r in self.store.rows('SELECT account_id,id,likes FROM append_baseline') if r['likes'] is None or r['likes']>self.config['threshold']}
            approved={(str(v.get('account_id','')),str(v.get('id',''))) for v in self.config['append_policy'].get('approved_historical_works', [])}
            rows = [r for r in rows if r.get('work_status')!='baseline_ignored' or (r['account_id'],r['id']) not in ignored or (r['account_id'],r['id']) in approved]
        fresh = [r for r in rows if not r['detail_checked']]
        def refresh_priority(row):
            display=json.loads(row['payload']).get('likes_exact_display')
            crossed=isinstance(display,int) and display>self.config['threshold'] and row.get('previous_likes') is not None and row['previous_likes']<=self.config['threshold']
            interval=count_interval(json.loads(row['payload']).get('likes_display',''))
            potential=interval is None or interval[1] is None or interval[1]>self.config['threshold']
            return (not crossed,not potential,row['detail_checked'])
        old = sorted((r for r in rows if r['detail_checked']),key=refresh_priority)
        reserved = min(len(old), max(1, limit//3)) if fresh and limit else min(len(old),limit)
        buckets = {}
        for row in fresh:
            buckets.setdefault(row['account_id'],[]).append(row)
        for bucket in buckets.values():
            bucket.sort(key=lambda r:((json.loads(r['payload']).get('likes_exact_display') is not None and json.loads(r['payload'])['likes_exact_display']<=self.config['threshold']),bool(json.loads(r['payload']).get('is_pinned')),
                json.loads(r['payload']).get('listing_order',1000000),r['id']))
        chosen = []
        while len(chosen) < max(0,limit-reserved) and any(buckets.values()):
            for account in sorted(buckets):
                if buckets[account] and len(chosen)<limit-reserved:
                    chosen.append(buckets[account].pop(0))
        chosen.extend(old[:max(0,limit-len(chosen))])
        return chosen[:limit]


    def export_descriptions(self):
        paths, index_entries = [], []
        for row in self.store.rows('SELECT * FROM works WHERE likes>?', (self.config['threshold'],)):
            work = json.loads(row['payload'])
            if work.get('source') != 'browser' or not work.get('detail_verified') or not work.get('description_complete'):
                continue
            from .wps import marker
            tag = marker(row['account_id'], row['id'])
            path = self.root / 'publishing-copy' / (tag.split(':')[1] + '.md')
            path.parent.mkdir(exist_ok=True)
            text = '\n\n'.join([f'<!-- {tag} -->', '# 已核验发布文案',
                '范围：发布时填写的文字描述；不包含视频口播逐字稿或图片内文字。',
                f"账号：{work['account_name']}", f"作品：{work['url']}",
                f"发布时间（页面本地时间）：{work['published_at']}",
                f"点赞数（详情页显示）：{row['likes']}", f"采集时间：{row['checked_at']}",
                '## 发布文案', work['description']])
            temp = path.with_suffix('.tmp');temp.write_text(text,encoding='utf-8');temp.replace(path)
            paths.append(str(path))
            index_entries.append(f"- [{work['account_name']} | {work['id']} | {row['likes']}赞]({path.name})")
        index_path = self.root / 'publishing-copy' / 'index.md'
        if paths:
            index_path.write_text('# 已核验发布文案\n\n以下仅为发布描述，不含视频逐字稿或图片内文字；尚未写入金山文档。\n\n' + '\n'.join(index_entries), encoding='utf-8')
        return {'index': str(index_path) if paths else None, 'destination':'local_publishing_copy','files':paths,'remote_archived':False,
                'includes_transcript':False,'includes_image_ocr':False}

    def run(self, historical=False, max_scrolls=4, max_details=6):
        if not 0 <= max_scrolls <= 200 or not 0 <= max_details <= 100:
            raise ValueError('browser budgets out of bounds')
        from playwright.sync_api import sync_playwright
        scans, checked, issues, blocked = [], 0, [], None
        with sync_playwright() as p:
            try:
                context = p.chromium.launch_persistent_context(browser_options(self.service.config,self.root)[0],
                    channel=browser_options(self.service.config,self.root)[1], headless=False, locale='zh-CN')
            except Exception:
                raise RuntimeError('browser_unavailable: close the probe browser before retrying; check Edge installation') from None
            try:
                profiles = [v for v in self.config.get('public_profiles', []) if v.get('name_verified') and v.get('name')]
                for profile in profiles:
                    page = context.new_page()
                    try:
                        progress('正在扫描账号主页：'+profile['name'])
                        scans.append(self.scan_profile(page, profile, historical, max_scrolls))
                    except BrowserBlocked as exc:
                        blocked = str(exc); break
                    except Exception as exc:
                        issues.append({'profile': profile['name'], 'error': type(exc).__name__})
                    finally:
                        page.close()
                if not blocked:
                    detail_queue=self.pending(max_details)
                    for detail_index,row in enumerate(detail_queue,1):
                        progress(f'正在核验作品 {detail_index}/{len(detail_queue)}')
                        card = json.loads(row['payload']);page = context.new_page()
                        try:
                            work = self.detail(page, card)
                            self.service.ingest([work], 'browser')
                            checked += 1; status, error = 'verified', None
                        except BrowserBlocked as exc:
                            blocked = str(exc); break
                        except Exception as exc:
                            status = 'review_required'
                            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                            attempt_path=self.root/'browser-detail-attempts'/(card['id']+'.json')
                            if error=='detail_author_mismatch' and attempt_path.is_file() and confirmed_other_author(card,json.loads(attempt_path.read_text(encoding='utf-8'))):
                                status='excluded_other_author';error='作品详情属于其他作者，未归入本账号'
                            else:issues.append({'work': card['id'], 'error': error})
                        finally:
                            page.close()
                        self.store.execute('UPDATE browser_candidates SET detail_checked=?,detail_status=?,error=? WHERE account_id=? AND id=?',
                            (now(), status, error, row['account_id'], row['id']))
            finally:
                context.close()
        scope_ids={PUBLIC_PREFIX+p['sec_uid'] for p in self.config.get('public_profiles',[])}
        unverified=[{'id':r['id'],'account_id':r['account_id'],'error':r['error']} for r in self.store.rows("SELECT id,account_id,error FROM browser_candidates WHERE detail_status IS NULL OR detail_status NOT IN ('verified','excluded_other_author')") if r['account_id'] in scope_ids]
        excluded=[{'id':r['id'],'reason':r['error']} for r in self.store.rows("SELECT id,error FROM browser_candidates WHERE detail_status='excluded_other_author'")]
        result = {'monitor': 'browser_action_required' if blocked else ('browser_partial' if issues or not scans or any(not s['historical_complete'] for s in scans) else 'browser_verified'),
            'profiles': scans, 'details_verified': checked, 'issues': issues, 'blocked': blocked,'unverified_candidates':unverified,'unverified_count':len(unverified),'excluded_other_authors':excluded,
            'remote_archived': False, 'checked_at': now()}
        if blocked or issues:
            self.store.event('browser_attention', json.dumps({'blocked': blocked, 'issues': issues}, ensure_ascii=False))
        for scan in scans:
            profile = next(p for p in self.config['public_profiles'] if p['name'] == scan['name'])
            self.store.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?)',
                (PUBLIC_PREFIX + profile['sec_uid'], profile['name'], result['monitor'], result['checked_at'], blocked))
        self.store.set('browser_last_run', result)
        return result