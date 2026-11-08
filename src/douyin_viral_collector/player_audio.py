"""Record only the verified ordinary browser video's own audio stream."""
import base64,json,hashlib
from pathlib import Path
from urllib.parse import urlsplit

def record_visible_audio(page,work,root):
 import av
 expected='/video/'+str(work['id']);assert work.get('detail_verified') and urlsplit(page.url).path.rstrip('/')==expected
 videos=page.locator('video:visible');candidates=[]
 for i in range(videos.count()):
  v=videos.nth(i);b=v.bounding_box()
  if b and b['width']>=150 and b['height']>=200:candidates.append(v)
 if len(candidates)!=1:raise ValueError('Active video is ambiguous')
 v=candidates[0];duration=v.evaluate('(v)=>v.duration');assert duration and 1<duration<=600,'Recording duration out of budget'
 result=v.evaluate('''async(v,expected)=>{
  if(location.pathname.replace(/\\/$/,'')!==expected)throw new Error('Work changed');
  if(typeof v.captureStream!=='function')throw new Error('Player does not allow ordinary audio capture');
  v.pause();v.playbackRate=1;
  if(v.currentTime>.03)await new Promise((resolve,reject)=>{let timer=setTimeout(()=>reject(new Error('Player rewind incomplete')),8000);v.addEventListener('seeked',()=>{clearTimeout(timer);resolve()},{once:true});v.currentTime=0;});
  let stream=v.captureStream(),tracks=stream.getAudioTracks();
  if(tracks.length!==1||tracks[0].muted)throw new Error('Player audio unavailable or capture restricted');
  let audio=new MediaStream(tracks),chunks=[],recorder=new MediaRecorder(audio,{mimeType:'audio/webm;codecs=opus'}),duration=v.duration,started=performance.now();
  return await new Promise((resolve,reject)=>{
   let complete=false,failed=null,lastTime=v.currentTime,startUrl=location.href;
   let monitor=setInterval(()=>{let same=location.pathname.replace(/\\/$/,'')===expected;if(same)lastTime=Math.max(lastTime,v.currentTime);if(!same){complete=lastTime>=duration-1;if(!complete)failed='Work changed before audio completed';if(recorder.state!=='inactive')recorder.stop();}},200);
   let timer=setTimeout(()=>{failed='Recording incomplete: time budget exceeded';if(recorder.state!=='inactive')recorder.stop()},(duration*2+60)*1000);
   let ended=()=>{complete=v.currentTime>=duration-1&&location.pathname.replace(/\\/$/,'')===expected;recorder.stop()};
   recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
   recorder.onerror=e=>{failed='Player recording failed';if(recorder.state!=='inactive')recorder.stop()};
   recorder.onstop=async()=>{clearTimeout(timer);clearInterval(monitor);v.removeEventListener('ended',ended,true);complete=complete||(lastTime>=duration-1&&(performance.now()-started)/1000>=duration*.97);if(failed||!complete)return reject(new Error(failed||'Player ended before complete recording'));let blob=new Blob(chunks,{type:'audio/webm'}),bytes=new Uint8Array(await blob.arrayBuffer()),pieces=[];for(let i=0;i<bytes.length;i+=32768)pieces.push(String.fromCharCode(...bytes.subarray(i,i+32768)));resolve({complete:true,duration,elapsed:(performance.now()-started)/1000,url:startUrl,final_url:location.href,observed_through:lastTime,base64:btoa(pieces.join(''))});};
   v.addEventListener('ended',ended,{once:true,capture:true});recorder.start(1000);v.play().catch(()=>{failed='Normal playback needs user action';recorder.stop()});
  });
 }''',expected)
 data=base64.b64decode(result.pop('base64'));folder=Path(root)/'player-recordings';folder.mkdir(exist_ok=True);path=folder/(hashlib.sha256((work['account_id']+str(work['id'])).encode()).hexdigest()+'.webm');pending=path.with_suffix('.partial.webm');pending.write_bytes(data)
 with av.open(str(pending)) as c:
  frames=list(c.decode(audio=0));assert frames,'No captured audio frames'
  first=min(f.time or 0 for f in frames);last=max((f.time or 0)+f.samples/f.sample_rate for f in frames);actual=last-first
  assert abs(actual-duration)<=max(2,duration*.01),'Recorded audio duration mismatch'
 assert result['elapsed']>=duration*.97,'Recording did not cover real-time playback'
 from douyin_viral_collector.media import ffmpeg_executable
 import subprocess
 assert not path.exists(),'Verified recording already exists'
 subprocess.run([ffmpeg_executable(),'-nostdin','-v','error','-n','-i',str(pending),'-map','0:a:0','-c:a','copy',str(path)],check=True,capture_output=True)
 result.update(source='verified_visible_player_audio_recording',account_id=work['account_id'],work_id=work['id'],path=str(path),decoded_seconds=actual,remuxed_without_reencoding=True)
 path.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
