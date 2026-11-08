import json,tempfile,unittest
from pathlib import Path
from docx import Document
from docx.shared import Pt
from douyin_viral_collector.document_settings import save_settings
from douyin_viral_collector.service import Service
from douyin_viral_collector.word_export import export_word
from douyin_viral_collector.richtext import archive_html
class DocumentSettingsTests(unittest.TestCase):
 def test_existing_doc_preserved_and_new_content_customized(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);original=root/'original.docx';doc=Document();doc.styles['Normal'].font.name='Arial';doc.styles['Normal'].font.size=Pt(12);p=doc.add_paragraph('用户已有原文');p.runs[0].bold=True;doc.save(original);old=original.read_bytes()
   cfg={'mode':'import','accounts':[],'minimum_likes':500,'data_dir':'data','wps':{'enabled':False},'word_export':{'base_document':str(original)},'document_format':{'font':'黑体','body_size':12,'heading_size':16,'line_spacing':1.5,'article_gap':18,'account_page_break':False,'inherit_existing':False}};(root/'config.json').write_text(json.dumps(cfg),encoding='utf-8');service=Service(root/'config.json')
   try:
    result=export_word(service,records=[{'id':'x','account_name':'示例','likes':600,'published_at':'2026-10-01','body':'新稿正文'}]);new=Document(result['path']);self.assertEqual(original.read_bytes(),old);self.assertEqual(new.paragraphs[0].text,'用户已有原文');self.assertTrue(new.paragraphs[0].runs[0].bold);self.assertEqual(new.styles['Normal'].font.name,'Arial');body=new.paragraphs[-1];self.assertEqual(body.runs[0].font.name,'黑体');self.assertEqual(body.runs[0].font.size.pt,12);self.assertEqual(body.paragraph_format.line_spacing,1.5)
   finally:service.store.db.close()
 def test_shared_target_validation_and_backup(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cfg={'data_dir':'data'};(root/'config.json').write_text(json.dumps(cfg),encoding='utf-8')
   with self.assertRaises(ValueError):save_settings(root,url='https://example.com/other',cloud=True,title='示例')
   saved=save_settings(root,url='https://www.kdocs.cn/l/example',title='示例文档',cloud=True,font='Arial',body_size=11);self.assertTrue(saved['wps']['enabled']);self.assertEqual(saved['document_format']['body_size'],11);self.assertTrue(list(root.glob('config.json.backup-*')))
 def test_cloud_html_uses_selected_format(self):
  result=archive_html(['示例账号','2026年10月1日，点赞600','正文'],['示例账号'],{'font':'Arial','body_size':12,'heading_size':18,'line_spacing':1.5,'article_gap':20,'account_page_break':False});self.assertIn('font-size:18pt',result);self.assertIn('font-size:12pt',result);self.assertIn('line-height:150.0%',result);self.assertNotIn('page-break-before:always',result)
