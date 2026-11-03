import unittest
from unittest.mock import Mock
from douyin_viral_collector.wps_browser import inspect_wps_page


class WPSPermissionTests(unittest.TestCase):
    def page(self, labels, title='口播逐字稿（已火）'):
        page=Mock();page.title.return_value=title;page.url='https://www.kdocs.cn/l/example-document'
        def nodes(text,exact=True):
            result=Mock();result.count.return_value=int(text in labels)
            result.nth.return_value.is_visible.return_value=text in labels
            return result
        page.get_by_text.side_effect=nodes
        return page

    def test_signed_out_cannot_pass_edit_gate(self):
        report=inspect_wps_page(self.page({'立即登录','可编辑'}))
        self.assertEqual(report['state'],'login_required')
        self.assertFalse(report['production_write_enabled'])

    def test_comment_only_requires_edit_permission(self):
        report=inspect_wps_page(self.page({'可评论'}))
        self.assertEqual(report['state'],'edit_permission_required')

    def test_edit_label_still_requires_test_and_backup(self):
        report=inspect_wps_page(self.page({'可编辑'}))
        self.assertEqual(report['state'],'test_document_required')
        self.assertFalse(report['test_append_verified'])
        self.assertFalse(report['original_file_backup_verified'])
        self.assertFalse(report['production_write_enabled'])

    def test_wrong_document_is_not_accepted(self):
        report=inspect_wps_page(self.page({'可编辑'},title='另一个文档'))
        self.assertEqual(report['state'],'document_not_verified')
    def test_same_title_different_share_link_is_not_target(self):
        page=self.page({'可编辑'});page.url='https://www.kdocs.cn/l/another-document'
        self.assertFalse(inspect_wps_page(page)['target_matches'])
