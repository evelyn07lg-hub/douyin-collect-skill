"""Conservative confidence gate for audio-only automatic punctuation review."""
from statistics import mean

def audio_quality(result):
 segments=result.get('timing',{}).get('segments',[])
 probabilities=[float(w['probability']) for s in segments for w in s.get('words',[]) if w.get('probability') is not None and str(w.get('word','')).strip()]
 reasons=[]
 if not probabilities:reasons.append('缺少词级置信度，需要补充素材或复核')
 average=mean(probabilities) if probabilities else 0
 low=sum(p<.4 for p in probabilities)/max(1,len(probabilities))
 if average<.72 or low>.3:reasons.append('口播置信度不足')
 if any(float(s.get('no_speech_prob',0))>.8 for s in segments):reasons.append('可能含非语音或静音误识别')
 if any(float(s.get('compression_ratio',0))>3 for s in segments):reasons.append('可能含重复识别')
 return {'accepted':not reasons,'mean_word_probability':average,'low_confidence_fraction':low,'reasons':reasons,'human_reviewed':False}
