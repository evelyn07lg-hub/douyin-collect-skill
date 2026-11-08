"""Time-align narration with author-edited captions; reference copy is supporting evidence."""
import bisect
import difflib
import functools
import re


def lexical(text):return ''.join(c.lower() for c in text if c.isalnum())


@functools.lru_cache(maxsize=5000)
def sound(character):
    if '\u4e00'<=character<='\u9fff':
        from pypinyin import lazy_pinyin
        return lazy_pinyin(character)[0]
    return character.lower()


def audio_characters(result):
    chars=[];times=[]
    for segment in result.get('timing',{}).get('segments',[]):
        words=segment.get('words') or [{'word':segment['text'],'start':segment['start'],'end':segment['end']}]
        for word in words:
            text=''.join(c for c in word.get('word','') if c.isalnum());start=float(word['start']);end=float(word['end'])
            for i,char in enumerate(text):
                chars.append(char);times.append(start+(end-start)*(i+.5)/max(1,len(text)))
    if not chars:raise ValueError('Timed narration is required for caption reconciliation')
    return chars,times


def align(caption,chars,times,start,end,cursor):
    """Semi-global edit alignment with homophone cost and a time-based tie-breaker."""
    query=list(lexical(caption));lo=max(cursor,bisect.bisect_left(times,max(0,start-1.2)))
    hi=bisect.bisect_right(times,end+1.2)
    target=chars[lo:hi]
    if not query or not target:return None
    previous=[0.]*(len(target)+1);beginnings=list(range(len(target)+1))
    for i,q in enumerate(query,1):
        current=[float(i)];starts=[0]
        for j,c in enumerate(target,1):
            cost=0 if q.lower()==c.lower() else .2 if sound(q)==sound(c) else 1
            options=[(previous[j-1]+cost,beginnings[j-1]),(previous[j]+1,beginnings[j]),(current[j-1]+1,starts[j-1])]
            value,origin=min(options,key=lambda x:x[0]);current.append(value);starts.append(origin)
        previous,beginnings=current,starts
    candidates=[]
    middle=(start+end)/2
    for j in range(1,len(target)+1):
        origin=beginnings[j]
        if j<=origin:continue
        distance=abs((times[lo+origin]+times[lo+j-1])/2-middle)
        candidates.append((previous[j]/max(len(query),j-origin)+min(distance,3)*.04,lo+origin,lo+j,previous[j]/max(len(query),j-origin)))
    if not candidates:return None
    _,a,b,error=min(candidates)
    return {'start':a,'end':b,'error':error,'audio':' '.join(chars[a:b])}


def repair_ocr_confusions(caption,spoken,library):
    """Repair short glyph/phonetic errors only with spoken and common-word support."""
    import jieba
    jieba.initialize()
    text=lexical(caption);audio=lexical(spoken);positions=[i for i,c in enumerate(caption) if c.isalnum()]
    anchors=[v for v in difflib.SequenceMatcher(None,text,audio,autojunk=False).get_matching_blocks() if v.size>=2]
    if anchors:
        anchor=max(anchors,key=lambda block:block.size);offset=max(0,anchor.b-anchor.a);audio=audio[offset:offset+len(text)]
    changes=[];shapes={frozenset(x) for x in ['日目','己已','未末','土士','候侯','遍逼','才打']}
    for op,a,b,c,d in difflib.SequenceMatcher(None,text,audio,autojunk=False).get_opcodes():
        if op!='replace' or b-a!=1 or d-c!=1:continue
        old_char,new_char=text[a],audio[c]
        if not all('\u4e00'<=v<='\u9fff' for v in (old_char,new_char)):continue
        if any(v in '今明昨前年月日时周一二三四五六七八九十百千万亿我你他她它这那谁哪不没未无' for v in (old_char,new_char)) and frozenset((old_char,new_char)) not in shapes:continue
        phonetic=difflib.SequenceMatcher(None,sound(old_char),sound(new_char)).ratio()
        if frozenset((old_char,new_char)) not in shapes and phonetic<.75:continue
        lo=max(0,a-4);hi=min(len(text),b+4);old=text[lo:hi];relative=a-lo;new=old[:relative]+new_char+old[relative+1:]
        def words(value):
            return [value[x:y] for x in range(max(0,relative-3),relative+1) for y in range(relative+1,min(len(value),x+4)+1) if y-x>=2 and (jieba.get_FREQ(value[x:y]) or 0)>=20]
        old_words=words(old);new_words=words(new)
        known_misspelling=any(x in old and old.index(x)<=relative<old.index(x)+len(x) for x in ('自已',))
        if old_words and not known_misspelling:continue
        if not new_words:continue
        if library and old in library.text and new not in library.text:continue
        supported=any((jieba.get_FREQ(w) or 0)>=500 or (library and w in library.text) for w in new_words)
        if not supported:continue
        pos=positions[a];changes.append({'start':pos,'end':pos+1,'before':caption[pos],'after':new_char,'method':'ocr_audio_and_common_word_context','reference_supported':bool(library and any(w in library.text for w in new_words)),'context_inference':True})
    for change in reversed(changes):caption=caption[:change['start']]+change['after']+caption[change['end']:]
    return caption,changes


def trim_unspoken_visual_edges(caption,spoken):
    query=lexical(caption);audio=lexical(spoken)
    if not audio:return caption,None
    blocks=[b for b in difflib.SequenceMatcher(None,query,audio,autojunk=False).get_matching_blocks() if b.size>=2]
    if not blocks or sum(b.size for b in blocks)<len(audio)*.6:return caption,None
    start=min(b.a for b in blocks);end=max(b.a+b.size for b in blocks)
    removed=query[:start]+query[end:]
    if len(removed)<4:return caption,None
    interface_text=bool(re.search(r'评价内容|主评|一星|二星|三星|四星|五星',removed))
    if not interface_text and (len(query)<=len(audio)*1.5+6 or len(removed)<8):return caption,None
    positions=[i for i,c in enumerate(caption) if c.isalnum()];trimmed=caption[positions[start]:positions[end-1]+1]
    return trimmed,{'before':caption,'after':trimmed,'method':'visual_edges_outside_spoken_alignment','raw_caption_preserved':True}


def repair_reference_audio_phrases(caption,spoken,library,protected_terms=()):
    """Prefer a domain phrase only when narration and reference independently agree."""
    if library is None:return caption,[]
    text=lexical(caption);audio=lexical(spoken);positions=[i for i,c in enumerate(caption) if c.isalnum()]
    matcher=difflib.SequenceMatcher(None,text,audio,autojunk=False);blocks=[b for b in matcher.get_matching_blocks() if b.size>=2]
    if not blocks:return caption,[]
    anchor=max(blocks,key=lambda b:b.size);offset=max(0,anchor.b-anchor.a);audio=audio[offset:offset+len(text)]
    changes=[]
    for op,a,b,c,d in difflib.SequenceMatcher(None,text,audio,autojunk=False).get_opcodes():
        if op!='replace' or not 1<=b-a<=3 or b-a!=d-c:continue
        old,new=text[a:b],audio[c:d]
        if not all('\u4e00'<=v<='\u9fff' for v in old+new):continue
        if any(v in '今明昨前年月日时周一二三四五六七八九十百千万亿我你他她它这那谁哪不没未无' for v in old+new):continue
        if difflib.SequenceMatcher(None,''.join(sound(v) for v in old),''.join(sound(v) for v in new)).ratio()<.5:continue
        lo,hi=positions[a],positions[b-1]+1
        if any(m.start()<hi and m.end()>lo for term in protected_terms for m in re.finditer(re.escape(term),caption)):continue
        supported=None
        for length in range(8,3,-1):
            for start in range(max(0,b-length),min(a,len(text)-length)+1):
                end=start+length;original=text[start:end];candidate=text[start:a]+new+text[b:end]
                if candidate in library.text and original not in library.text and candidate in lexical(spoken):
                    supported=candidate;break
            if supported:break
        if supported:changes.append({'start':lo,'end':hi,'before':caption[lo:hi],'after':new,
                'reference_phrase':supported,'context_inference':True,'method':'audio_reference_phrase_agreement'})
    for change in reversed(changes):caption=caption[:change['start']]+change['after']+caption[change['end']:]
    return caption,changes


def reconcile(asr,subtitles,library=None,minimum_coverage=.75,ocr_corrections=()):
    if subtitles.get('status')!='extracted':raise ValueError('Reliable video captions have not been extracted')
    chars,times=audio_characters(asr);cursor=0;parts=[];decisions=[];covered=0;used=0;aligned=0;accepted_intervals=[]
    cues=subtitles['cues']
    for index,cue in enumerate(cues):
        match=align(cue['text'],chars,times,cue['start'],cue['end'],cursor)
        fallback=False;visual_change=None;candidate=cue['text']
        if match:
            candidate,visual_change=trim_unspoken_visual_edges(candidate,''.join(chars[match['start']:match['end']]))
            if visual_change:match=align(candidate,chars,times,cue['start'],cue['end'],cursor)
        if not match or match['error']>.62:
            if (cue['confidence']>=.9 and cue.get('samples',1)>=2) or (cue['confidence']>=.8 and cue.get('samples',1)>=4):
                lo=max(cursor,bisect.bisect_left(times,max(0,cue['start']-.2)))
                hi=max(lo,bisect.bisect_right(times,cue['end']+.2))
                if hi-lo<3 or len(lexical(candidate))>max(12,(hi-lo)*1.7+3):
                    decisions.append({'caption':cue,'decision':'unsupported_visual_text','audio_match':match});continue
                match={'start':lo,'end':hi,'error':None,'audio':''.join(chars[lo:hi])}
                fallback=True
            else:
                decisions.append({'caption':cue,'decision':'unresolved_alignment','audio_match':match})
                continue
        else:aligned+=1
        a,b=match['start'],match['end']
        if a>cursor:
            gap=''.join(chars[k] for k in range(cursor,a) if not any(v['start']-.15<=times[k]<=v['end']+.15 for v in accepted_intervals+[cue]));changes=[]
            if library:gap,changes=library.correct(gap)
            parts.append({'source':'asr_gap','text':gap,'start':times[cursor], 'end':times[a-1], 'reference_changes':changes})
        chosen,changes=repair_ocr_confusions(candidate, ''.join(chars[a:b]),library)
        if visual_change:changes.append(visual_change)
        context=(cues[index-1]['text'] if index else '')+chosen+(cues[index+1]['text'] if index+1<len(cues) else '')
        protected_terms=[]
        for rule in ocr_corrections:
            if rule['before'] in chosen and (not rule.get('context') or re.search(rule['context'],context)):
                chosen=chosen.replace(rule['before'],rule['after']);protected_terms.append(rule['after'])
                changes.append({'before':rule['before'],'after':rule['after'],'method':'reviewed_visual_ocr_context_rule'})
        # Library suggestions cannot override the edited subtitle on their own.
        # A short spelling correction needs agreement from both the spoken words and
        # a matching reference passage; valid original words remain protected.
        if library:
            prefix=cues[index-1]['text'] if index else ''
            suffix=cues[index+1]['text'] if index+1<len(cues) else ''
            spoken=''.join(chars[max(0,a-20):min(len(chars),b+20)])
            chosen,phrase_changes=repair_reference_audio_phrases(chosen,spoken,library,protected_terms)
            changes.extend(phrase_changes)
            _,proposals=library.correct(prefix+chosen+suffix)
            for change in proposals:
                x,y=change['start']-len(prefix),change['end']-len(prefix)
                protected=any(a.start()<y and a.end()>x for term in protected_terms for a in re.finditer(re.escape(term),chosen))
                if not protected and 0<=x<y<=len(chosen) and lexical(change['after']) in spoken and lexical(change['before']) not in spoken:
                    changes.append(dict(change,start=x,end=y,method='audio_and_reference_agree'))
            for change in reversed([v for v in changes if v['method']=='audio_and_reference_agree']):chosen=chosen[:change['start']]+change['after']+chosen[change['end']:]
        parts.append({'source':'author_video_caption','text':chosen,'start':cue['start'],'end':cue['end'],
                      'ocr_text':cue['text'],'confidence':cue['confidence'],'three_way_changes':changes})
        decisions.append({'caption':cue,'decision':'caption_primary_time_fallback' if fallback else 'caption_primary','audio_match':match,'three_way_changes':changes})
        cursor=b;covered+=b-a;used+=1;accepted_intervals.append(cue)
    if cursor<len(chars):
        gap=''.join(chars[k] for k in range(cursor,len(chars)) if not any(v['start']-.15<=times[k]<=v['end']+.15 for v in accepted_intervals));changes=[]
        if library:gap,changes=library.correct(gap)
        parts.append({'source':'asr_gap','text':gap,'start':times[cursor],'end':times[-1],'reference_changes':changes})
    coverage=covered/max(1,len(chars));accepted_ratio=used/max(1,len(cues));agreement_ratio=aligned/max(1,len(cues))
    # Refuse to publish a transcript represented as caption-led when most captions
    # or most narration could not be aligned. Keep all raw sources for review instead.
    if coverage<minimum_coverage or accepted_ratio<.8 or agreement_ratio<.8:
        raise ValueError(f'Caption coverage needs review: narration={coverage:.1%}, accepted_cues={accepted_ratio:.1%}')
    return dict(asr,body=''.join(p['text'] for p in parts),subtitle_primary=True,
                subtitle_reconciliation={'priority':['author_video_caption','spoken_audio','reference_library'],
                  'narration_caption_coverage':coverage,'accepted_caption_ratio':accepted_ratio,'audio_caption_agreement_ratio':agreement_ratio,
                  'caption_count':used,'parts':parts,'decisions':decisions,'raw_asr_preserved':True,
                  'reference_sha256':library.sha256 if library else None,'human_reviewed':False})
