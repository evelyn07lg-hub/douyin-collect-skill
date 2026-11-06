import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from douyin_viral_collector.proofreading import Proofreader,ReferenceLibrary,lexical
from douyin_viral_collector.richtext import archive_html
from douyin_viral_collector.wps import format_paragraphs

class ProofreadingTests(unittest.TestCase):
    def reader(self, reference='', punctuator=None, rules=()):
        p=Proofreader.__new__(Proofreader)
        p.settings={'reviewed_replacements':list(rules)}
        p.library=ReferenceLibrary(reference) if reference else None
        p.punctuator=punctuator
        return p

    def test_raw_is_preserved_and_reference_cannot_add_unsaid_sentences(self):
        text='先找到适合自己的方向以后再去行动不要盲目地追逐所谓的风口'
        p=self.reader(text+'这是素材库里面额外写的但是视频没有讲的句子')
        result=p.process({'raw':text,'body':text})
        self.assertEqual(result['raw'],text)
        self.assertEqual(result['body'],text)

    def test_source_typos_do_not_overwrite_correct_words(self):
        source='这个行业已经开始走向正轨所以我们可以按照自己的节奏坚持做下去不要急'
        p=self.reader(source.replace('正轨','正规'))
        self.assertEqual(p.process({'raw':source,'body':source})['body'],source)

    def test_unrelated_reference_is_not_applied(self):
        p=self.reader('完全不一样的主题我们今天讨论旅游和美食还有天气')
        text='我正在讲自己创业的经历资金压力和产品销售没有谈论其他的事情'
        self.assertEqual(p.process({'raw':text,'body':text})['body'],text)

    def test_context_rule_and_punctuation_keep_evidence(self):
        p=self.reader(punctuator=lambda text:(text+'。',[]),rules=[{'before':'回责标本','after':'蝴蝶标本','context':'标本'}])
        text='我做的是回责标本'
        result=p.process({'raw':text,'body':text})
        self.assertEqual(result['body'],'我做的是蝴蝶标本。')
        self.assertEqual(result['raw'],text)
        self.assertTrue(result['proofreading']['changes'][0]['corrections'])

    def test_punctuation_cannot_delete_or_invent_words(self):
        p=self.reader(punctuator=lambda text:('另外一篇完全不同的正文。',[]))
        with self.assertRaises(ValueError):p.process({'raw':'原始口播内容','body':'原始口播内容'})

    def test_publisher_copy_is_preserved(self):
        p=self.reader(punctuator=Mock(side_effect=AssertionError('no punctuation rewrite')))
        text={'raw':'发布文案！','body':'发布文案！','source':'published_description'}
        self.assertEqual(p.process(text),text)

    def test_existing_punctuation_and_manual_wording_are_retained(self):
        p=self.reader(punctuator=Mock(side_effect=AssertionError('already punctuated')))
        body='某鱼的事情，我们已经讲过了。respect兄弟！'
        self.assertEqual(p.process({'raw':body,'body':body})['body'],body)

    def test_missing_configured_reference_does_not_silently_skip(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RuntimeError):Proofreader({'reference_path':'missing.docx'},root)

    def test_html_escapes_content_and_assigns_only_account_page_breaks(self):
        result=archive_html(['账号一','正文<a>&标题'],['账号一'])
        self.assertEqual(result.count('page-break-before:always'),1)
        self.assertIn('font-size:14pt',result)
        self.assertIn('font-size:10.5pt',result)
        self.assertIn('正文&lt;a&gt;&amp;标题',result)
        self.assertNotIn('<p></p>',result)

    def test_reflow_has_no_empty_paragraphs_and_preserves_words(self):
        text='第一部分，完整内容。\n\n第二段继续。\n最后补充。'
        result=format_paragraphs(text,target_length=8)
        self.assertNotIn('\n\n',result)
        self.assertEqual(lexical(text),lexical(result))

if __name__=='__main__':unittest.main()
