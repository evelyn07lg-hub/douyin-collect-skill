"""Accept ordinary Douyin share text; resolve links through the visible browser."""
import re
from pathlib import Path
from urllib.parse import urlsplit


def extract_links(text):
    text = str(text).replace('\\:', ':').replace('\\/', '/')
    urls = re.findall(r'https?://(?:v\.douyin\.com|(?:www\.)?douyin\.com)/[^\s<>\[\]"，。；;]+', text, re.I)
    urls = [u.rstrip(');）！!') for u in urls]
    if not urls:
        raise ValueError('没有找到抖音链接，请直接粘贴抖音复制的完整分享文字。')
    return list(dict.fromkeys(urls))


def profile_url(url):
    p = urlsplit(url)
    if p.hostname not in ('douyin.com', 'www.douyin.com'):
        return None
    m = re.fullmatch(r'/user/([A-Za-z0-9_.-]+)/?', p.path)
    return 'https://www.douyin.com/user/' + m[1] if m else None


def resolve_profiles(inputs, root, config=None):
    urls = extract_links('\n'.join(inputs))
    results = [profile_url(u) for u in urls]
    if all(results):
        return list(dict.fromkeys(results))
    import sys
    from .browser_choice import browser_options
    from playwright.sync_api import sync_playwright
    from .storage import lock
    with lock(Path(root) / 'collect.lock'):
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(browser_options(config or {},root)[0],
                channel=browser_options(config or {},root)[1], headless=False, locale='zh-CN')
            try:
                page = context.new_page()
                for i, url in enumerate(urls):
                    if results[i]:continue
                    try:
                        page.goto(url,wait_until='domcontentloaded',timeout=45000)
                    except Exception:
                        pass  # Inspect the actual page after normal redirects.
                    page.wait_for_timeout(4000)
                    target = profile_url(page.url)
                    if target:
                        results[i]=target;continue
                    if urlsplit(page.url).hostname not in ('www.douyin.com','douyin.com'):
                        raise ValueError('短链接尚未展开为抖音页面，请完成浏览器验证后重试。')
                    candidates = page.locator('[data-e2e="video-author-name"], [data-e2e="user-info"] a[href*="/user/"], [data-e2e="note-author-name"]')
                    authors = set()
                    for node in candidates.all():
                        href=node.get_attribute('href')
                        if not href:href=node.locator('a[href*="/user/"]').first.get_attribute('href') if node.locator('a[href*="/user/"]').count() else None
                        if href:
                            found=profile_url('https://www.douyin.com'+href if href.startswith('/') else href)
                            if found:authors.add(found)
                    if len(authors)!=1:
                        raise ValueError('已提取分享链接，但暂时无法唯一确认作品作者。请完成浏览器登录/验证后重试，或粘贴作者主页分享链接。')
                    results[i]=authors.pop()
            finally:
                context.close()
    return list(dict.fromkeys(results))
