import copy,json,tempfile,unittest,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock,patch
from douyin_viral_collector.wps_integrity import snapshot,verify_section_append,NS,W
from douyin_viral_collector.wps_writer import WPSBrowserWriter
from douyin_viral_collector.service import Service


def fixture(path,texts,style='fixed',font='宋体'):
    root=ET.Element(W+'document');body=ET.SubElement(root,W+'body')
    for text in texts:
        p=ET.SubElement(body,W+'p');props=ET.SubElement(p,W+'pPr');ET.SubElement(props,W+'jc',{W+'val':'left'})
        r=ET.SubElement(p,W+'r');pr=ET.SubElement(r,W+'rPr');ET.SubElement(pr,W+'rFonts',{W+'eastAsia':font});ET.SubElement(r,W+'t').text=text
    ET.SubElement(body,W+'sectPr')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml',ET.tostring(root));z.writestr('word/styles.xml',style)
        z.writestr('word/fontTable.xml',f'<w:fonts xmlns:w="{NS["w"]}"><w:font w:name="宋体"/></w:fonts>')
    return snapshot(path)


class WPSIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old=['甲','旧甲','乙','旧乙','丙','旧丙'];self.lines=['日期 点赞501','视频','标题','完整正文']
        self.before=fixture(self.root/'before.docx',self.old)
    def tearDown(self):self.tmp.cleanup()
    def test_only_account_boundary_insert_passes(self):
        after=fixture(self.root/'after.docx',self.old[:2]+self.lines+self.old[2:])
        self.assertTrue(verify_section_append(self.before,after,self.lines,'甲',['甲','乙','丙'])['existing_format_preserved'])
        with self.assertRaises(ValueError):verify_section_append(self.before,after,self.lines,'乙',['甲','乙','丙'])
    def test_old_text_change_is_rejected(self):
        values=self.old[:2]+self.lines+self.old[2:];values[1]='改掉了旧甲'
        with self.assertRaises(ValueError):verify_section_append(self.before,fixture(self.root/'after.docx',values),self.lines,'甲',['甲','乙','丙'])
    def test_old_font_change_is_rejected(self):
        after=fixture(self.root/'after.docx',self.old[:2]+self.lines+self.old[2:],font='黑体')
        with self.assertRaises(ValueError):verify_section_append(self.before,after,self.lines,'甲',['甲','乙','丙'])
    def test_missing_inserted_text_is_rejected(self):
        after=fixture(self.root/'after.docx',self.old[:2]+self.lines[:-1]+self.old[2:])
        with self.assertRaises(ValueError):verify_section_append(self.before,after,self.lines,'甲',['甲','乙','丙'])
    def test_style_change_is_rejected(self):
        after=fixture(self.root/'after.docx',self.old[:2]+self.lines+self.old[2:],style='changed')
        with self.assertRaises(ValueError):verify_section_append(self.before,after,self.lines,'甲',['甲','乙','丙'])


    def split_old_run(self, path, change_format=False, change_text=False):
        with zipfile.ZipFile(path) as source:
            files = {name: source.read(name) for name in source.namelist()}
        document = ET.fromstring(files['word/document.xml'])
        paragraph = document.find('w:body', NS).findall('w:p', NS)[1]
        original = paragraph.find('w:r', NS)
        trailing = copy.deepcopy(original)
        original.find('w:t', NS).text = '旧'
        trailing.find('w:t', NS).text = '乙' if change_text else '甲'
        if change_format:
            trailing.find('w:rPr/w:rFonts', NS).set(W+'eastAsia', '黑体')
        paragraph.append(trailing)
        files['word/document.xml'] = ET.tostring(document)
        with zipfile.ZipFile(path, 'w') as target:
            for name, content in files.items(): target.writestr(name, content)
        return snapshot(path)

    def test_equal_character_format_survives_editor_run_splitting(self):
        path = self.root/'after.docx'
        fixture(path,self.old[:2]+self.lines+self.old[2:])
        after = self.split_old_run(path)
        self.assertTrue(verify_section_append(self.before,after,self.lines,'甲',['甲','乙','丙'])['existing_format_preserved'])

    def test_run_merge_does_not_hide_character_font_change(self):
        path = self.root/'after.docx'
        fixture(path,self.old[:2]+self.lines+self.old[2:])
        with self.assertRaises(ValueError):
            verify_section_append(self.before,self.split_old_run(path,True),self.lines,'甲',['甲','乙','丙'])

    def test_run_splitting_does_not_hide_old_text_change(self):
        path = self.root/'after.docx'
        fixture(path,self.old[:2]+self.lines+self.old[2:])
        after = self.split_old_run(path,change_text=True)
        with self.assertRaises(ValueError):
            verify_section_append(self.before,after,self.lines,'甲',['甲','乙','丙'])


class WPSJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        config=self.root/'config.json';config.write_text(json.dumps({'data_dir':'data','threshold':500,
          'accounts':[],'wps':{'url':'https://www.kdocs.cn/l/production','enabled':False},
          'public_profiles':[{'name':v,'name_verified':True,'sec_uid':v} for v in ['甲','乙','丙']]}),encoding='utf-8')
        self.s=Service(config);self.writer=WPSBrowserWriter(self.s,'https://www.kdocs.cn/l/test','test',True)
        self.before=fixture(self.root/'before.docx',['甲','旧甲','乙','旧乙','丙','旧丙'])
        self.work={'account_name':'甲','type':'video','title':'新标题','published_at':'2026-11-03','comments':0,'favorites':0,'shares':0}
        self.row={'account_id':'account','id':'work','likes':501,'body':'新内容'*100,'checked_at':'now'}
    def tearDown(self):self.s.store.db.close();self.tmp.cleanup()
    def test_test_mode_cannot_target_production(self):
        with self.assertRaises(ValueError):WPSBrowserWriter(self.s,test_only=True)
    def test_disabled_production_cannot_write(self):
        with self.assertRaises(RuntimeError):WPSBrowserWriter(self.s)
    def test_enabled_flag_alone_cannot_bypass_proof(self):
        self.s.config['wps']['enabled']=True
        with self.assertRaisesRegex(RuntimeError,'proof missing'):WPSBrowserWriter(self.s)
    def test_stale_writer_proof_is_rejected(self):
        self.s.config['wps']['enabled']=True
        proof=self.s.root/'wps-inspection/production-readiness.json';proof.parent.mkdir()
        proof.write_text(json.dumps({'source_document_url':self.s.config['wps']['url'],
            'account_section_append_verified':True,'existing_format_preserved':True,'validated_code_sha256':'stale'}))
        with self.assertRaisesRegex(RuntimeError,'stale'):WPSBrowserWriter(self.s)

    def test_uncertain_write_does_not_repeat(self):
        self.writer.record(self.row,'uncertain','未完成的内容',self.root/'before.docx')
        page=Mock()
        with patch.object(self.writer,'download',return_value=self.before):
            with self.assertRaisesRegex(RuntimeError,'no re-append'):self.writer.append(page,self.row,self.work)
        page.keyboard.press.assert_not_called();page.keyboard.insert_text.assert_not_called()
    def test_verification_failure_persists_uncertain(self):
        page=Mock()
        with patch.object(self.writer,'download',return_value=self.before),patch.object(self.writer,'position'),patch('douyin_viral_collector.wps_writer.verify_section_append',side_effect=ValueError('incomplete')):
            with self.assertRaisesRegex(RuntimeError,'no automatic re-append'):self.writer.append(page,self.row,self.work)
        self.assertEqual(self.s.store.rows('SELECT state FROM wps_write_jobs')[0]['state'],'uncertain')