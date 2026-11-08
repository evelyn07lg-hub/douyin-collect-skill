import unittest
from douyin_viral_collector.caption_layout import side_text_indices
from douyin_viral_collector.proofreading import project_spoken_punctuation,lexical

class CaptionLayoutTests(unittest.TestCase):
    def test_side_ad_is_removed_only_with_horizontal_caption(self):
        horizontal=([[300,200],[520,200],[520,240],[300,240]],'去去去走吧走',.99)
        vertical=([[700,180],[730,180],[730,300],[700,300]],'啤酒免费',.96)
        self.assertEqual(side_text_indices([horizontal,vertical],800),{1})
        self.assertEqual(side_text_indices([vertical],800),set())
    def test_punctuation_preserves_corrected_words_and_numbers(self):
        spoken='真的吗？真的，那行，你过户给我的话，前1000个粉丝。'
        body='真的吗真那行你过户给我的话前1000个粉丝'
        result,evidence=project_spoken_punctuation(spoken,body)
        self.assertEqual(lexical(result),lexical(body))
        self.assertIn('？',result)
        self.assertIn('1000',result)
