"""Manual login and public DOM evidence only; no private endpoints or bypass."""
import json
from datetime import datetime, timezone
from pathlib import Path


def navigate(page, url):
    """A redirect is evidence for manual review, never an invitation to bypass."""
    from playwright.sync_api import Error
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        return None
    except Error as exc:
        print('页面跳转未完成，请在浏览器中手动打开以下链接，或保留受阻页面以供检查：')
        print(url)
        return str(exc).split('Call log:')[0]


def main():
    from playwright.sync_api import sync_playwright
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config.json').read_text(encoding='utf-8-sig'))
    data = root / config['data_dir']
    output = data / 'browser-probe' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Separate profile: never attach to or copy the user's existing browser cookies.
        context = p.chromium.launch_persistent_context(str(data / 'browser-profile'),
            channel='msedge', headless=False, locale='zh-CN')
        try:
            page = context.pages[0] if context.pages else context.new_page()
            navigate(page, 'https://www.douyin.com/')
            input('请在弹出的 Edge 中使用另一个抖音账号自行登录，完成验证后在这里按回车。不要提供密码给程序。\n')
            for i, profile in enumerate(config['public_profiles'], 1):
                url = 'https://www.douyin.com/user/' + profile['sec_uid']
                page = context.new_page()
                navigation_error = navigate(page, url)
                input(f'主页{i}：请等待加载，核对昵称；若有验证请自行完成。加载成功或确定受阻后，按回车保存当前页面证据。\n')
                text = page.locator('body').inner_text(timeout=15000)
                evidence = {'sec_uid': profile['sec_uid'], 'requested_url': url,
                    'actual_url': page.url, 'title': page.title(), 'text': text,
                    'links': page.locator('a[href*="/video/"], a[href*="/note/"]').evaluate_all(
                        '(nodes) => nodes.map(n => ({url:n.href,text:n.innerText}))'),
                    'navigation_error': navigation_error,
                    'profile_url_matches': page.url.split('?')[0].rstrip('/') == url,
                    'status': 'manual_review_required', 'complete_history': False}
                (output / f'profile-{i}.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
                try:
                    page.screenshot(path=str(output / f'profile-{i}.png'), full_page=False)
                except Exception as exc:
                    print('截图失败，已保留页面JSON：' + type(exc).__name__)
                page.close()
            print(json.dumps({'ok': True, 'evidence_dir': str(output),
                'monitor': 'not_verified', 'message': '仅保存可见页面；未开始采集或归档'}, ensure_ascii=False))
        finally:
            context.close()


if __name__ == '__main__':
    main()
