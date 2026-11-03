"""Read-only WPS login/permission inspection. Never types into a document."""
from datetime import datetime, timezone
from pathlib import Path


def inspect_wps_page(page, expected_title='口播逐字稿（已火）', expected_url='https://www.kdocs.cn/l/example-document'):
    from urllib.parse import urlsplit
    def visible(text):
        nodes = page.get_by_text(text, exact=True)
        return any(nodes.nth(i).is_visible() for i in range(min(nodes.count(), 8)))
    title = page.title()
    actual, expected = urlsplit(page.url), urlsplit(expected_url)
    on_target = actual.hostname in ('www.kdocs.cn', 'kdocs.cn') and actual.path.rstrip('/') == expected.path.rstrip('/') and title == expected_title
    login_required = visible('立即登录') or visible('登录后继续')
    permission_labels = [label for label in ('可编辑', '可评论', '只读', '仅查看', '可查看') if visible(label)]
    if not on_target:
        state = 'document_not_verified'
    elif login_required:
        state = 'login_required'
    elif '可编辑' in permission_labels:
        state = 'test_document_required'
    elif any(label in permission_labels for label in ('可评论', '只读', '仅查看', '可查看')):
        state = 'edit_permission_required'
    else:
        state = 'permission_unverified'
    return {'document_title':title, 'target_matches':on_target,
        'login_required':login_required, 'permission_labels':permission_labels,
        'state':state,'production_write_enabled':False,
        'original_file_backup_verified':False,'test_append_verified':False,
        'checked_at':datetime.now(timezone.utc).isoformat()}


def login_and_inspect(service):
    from playwright.sync_api import sync_playwright
    from .browser import save_json
    url=service.config['wps']['url']
    with sync_playwright() as p:
        context=p.chromium.launch_persistent_context(str(service.root/'browser-profile'),
            channel='msedge',headless=False,locale='zh-CN')
        try:
            page=context.new_page()
            try:
                page.goto(url,wait_until='domcontentloaded',timeout=60000)
            except Exception:
                print('页面加载尚未完成，请在浏览器中确认目标文档。')
            print('请在弹出的 Edge 中点击“立即登录”，使用有权编辑这份文档的金山账号自行登录。')
            print('只完成登录和查看权限，不要在正式文档输入测试文字；密码或验证码无需提供给程序。')
            input('确认已回到“口播逐字稿（已火）”页面后，在此按回车；若受阻也可按回车记录当前状态。\n')
            page.wait_for_timeout(1500)
            report=inspect_wps_page(page, expected_url=url)
            save_json(service.root/'wps-inspection/readiness.json',report)
            service.store.set('wps_readiness',report)
            return report
        finally:
            context.close()