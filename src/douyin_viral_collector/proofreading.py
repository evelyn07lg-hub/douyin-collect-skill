"""Local reference-assisted ASR correction; publisher documents are data, never instructions."""
import difflib
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def lexical(text):
    return ''.join(c.lower() for c in text if c.isalnum())


def read_reference(path):
    path = Path(path)
    if path.suffix.lower() != '.docx':
        return path.read_text(encoding='utf-8-sig')
    w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as package:
        doc = ET.fromstring(package.read('word/document.xml'))
    # WPS uses soft line breaks inside very long paragraphs; retain their boundaries.
    return '\n'.join(''.join((e.text or '') if e.tag == w+'t' else '\n' if e.tag == w+'br' else ''
                            for e in paragraph.iter()) for paragraph in doc.iter(w+'p'))


class ReferenceLibrary:
    def __init__(self, text):
        from opencc import OpenCC
        self.text = lexical(OpenCC('t2s').convert(text))
        self.sha256 = hashlib.sha256(text.encode()).hexdigest()
        self.index = defaultdict(list)
        for i in range(max(0, len(self.text)-7)):
            self.index[self.text[i:i+8]].append(i)

    def candidates(self, source):
        votes = Counter()
        for i in range(0, max(0, len(source)-7), 8):
            locations = self.index.get(source[i:i+8], [])
            if len(locations) > 20:
                continue
            for position in locations:
                offset = position-i
                votes[round(offset/64)*64] += 1
        windows = []
        for offset, _ in votes.most_common(5):
            start = max(0, offset-160)
            windows.append((start, self.text[start:max(start, offset)+len(source)+160]))
        return windows

    def correct(self, text):
        source, positions = '', []
        for i, c in enumerate(text):
            if c.isalnum():
                source += c.lower(); positions.append(i)
        if len(source) < 24:
            return text, []
        best = None
        for start, candidate in self.candidates(source):
            matcher = difflib.SequenceMatcher(None, source, candidate, autojunk=False)
            blocks = matcher.get_matching_blocks()
            coverage = sum(b.size for b in blocks)/len(source)
            if best is None or coverage > best[0]:
                best = coverage, start, candidate, matcher
        if best is None or best[0] < .72:
            return text, []
        coverage, start, candidate, matcher = best
        from pypinyin import lazy_pinyin
        changes = []
        opcodes = matcher.get_opcodes()
        for k, (op, a, b, c, d) in enumerate(opcodes):
            if op != 'replace' or not (1 <= b-a <= 6 and b-a == d-c):
                continue
            old, new = source[a:b], candidate[c:d]
            if not all('\u4e00' <= char <= '\u9fff' for char in old+new):
                continue  # amounts, English, dates and ID strings never inferred
            left = opcodes[k-1] if k else None
            right = opcodes[k+1] if k+1 < len(opcodes) else None
            if not (left and right and left[0] == right[0] == 'equal' and
                    left[2]-left[1] >= 5 and right[2]-right[1] >= 5):
                continue
            phonetic = difflib.SequenceMatcher(None, ''.join(lazy_pinyin(old)), ''.join(lazy_pinyin(new))).ratio()
            if phonetic < .80:
                continue
            # The source library itself may contain mistakes. Keep already valid words,
            # and require the replacement to form a recognized multi-character word.
            import jieba
            if old in '他她它妳你得的地吗嘛哪那' and new in '他她它妳你得的地吗嘛哪那':
                continue
            old_context = source[max(0,a-6):min(len(source),b+6)]
            relative = min(6,a)
            valid_old = any(len(word)>=2 and lo<=relative and hi>=relative+len(old)
                            and (jieba.get_FREQ(word) or 0)>=10
                            for word,lo,hi in jieba.tokenize(old_context))
            new_context = source[max(0,a-6):a]+new+source[b:min(len(source),b+6)]
            valid_new = any(len(word)>=2 and lo<=relative and hi>=relative+len(new)
                            and (jieba.get_FREQ(word) or 0)>=10
                            for word,lo,hi in jieba.tokenize(new_context))
            if valid_old or not valid_new:
                continue
            lo, hi = positions[a], positions[b-1]+1
            if any(not ch.isalnum() for ch in text[lo:hi]):
                continue
            changes.append({'start': lo, 'end': hi, 'before': text[lo:hi], 'after': new,
                            'reference_offset': start+c, 'reference_coverage': round(coverage, 4),
                            'phonetic_similarity': round(phonetic, 4),
                            'context_inference': phonetic < 1})
        for edit in reversed(changes):
            text = text[:edit['start']] + edit['after'] + text[edit['end']:]
        return text, changes


class Proofreader:
    def __init__(self, settings, base):
        self.settings = settings
        self.base = Path(base)
        self.library = None
        if settings.get('reference_path'):
            reference = self.base / settings['reference_path']
            if not reference.is_file():
                raise RuntimeError('Configured reference library is unavailable; no unchecked archive')
            self.library = ReferenceLibrary(read_reference(reference))
        self.punctuator = None
        if settings.get('punctuation_model'):
            from funasr_onnx import CT_Transformer
            model = self.base / settings['punctuation_model']
            if not all((model/name).is_file() for name in ('model_quant.onnx','config.yaml','tokens.json')):
                raise RuntimeError('Local punctuation model is incomplete')
            self.punctuator = CT_Transformer(str(model), quantize=True, intra_op_num_threads=4)

    def process(self, result):
        if result.get('source') == 'published_description':
            return result  # published wording and punctuation remain authoritative
        original = result['body']
        output, evidence = [], []
        # Keep ASR fragments together for context; split only at bounded lengths.
        chunks = re.findall(r'[\s\S]{1,900}(?:[。！？\n]|$)|[\s\S]{1,900}', original)
        for chunk in chunks:
            corrected, changes = self.library.correct(chunk) if self.library else (chunk, [])
            for replacement in self.settings.get('reviewed_replacements', []):
                before, after = replacement['before'], replacement['after']
                if before and before in corrected:
                    if replacement.get('context') and not re.search(replacement['context'], corrected):
                        continue
                    corrected = corrected.replace(before, after)
                    changes.append({'before':before,'after':after,'method':'reviewed_context_rule',
                                    'context_inference':True})
            if self.punctuator:
                # Existing punctuation is retained when already reasonably punctuated.
                marks = sum(c in '，。！？；：,!?;' for c in corrected)
                sentences = sum(c in '。！？!?' for c in corrected)
                if marks/max(1,len(lexical(corrected))) < .025 or (len(corrected)>180 and sentences/max(1,len(lexical(corrected))) < 1/180):
                    unpunctuated = re.sub(r'[，。！？；：!?;]|(?<![0-9]),|,(?![0-9])', '', corrected)
                    punctuated, _ = self.punctuator(unpunctuated)
                    if lexical(punctuated) != lexical(corrected):
                        raise ValueError('Punctuation restoration changed spoken words')
                    corrected = punctuated
            output.append(corrected.strip())
            evidence.append({'corrections': changes})
        cleaned = '\n'.join(output)
        return dict(result, body=cleaned, proofreading={
            'method':'local_reference_alignment_and_ct_punc',
            'reference_sha256':self.library.sha256 if self.library else None,
            'raw_preserved':True, 'human_reviewed':False,
            'changes':evidence, 'punctuation_enabled':self.punctuator is not None})
