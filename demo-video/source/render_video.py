"""Compose the recorded browser walkthrough, chapter labels, and narration."""
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo-video'
WORK=Path(os.environ.get('DEMO_WORK','/private/tmp/gateway-video-work'))
FF=imageio_ffmpeg.get_ffmpeg_exe()
SCENES=json.loads((OUT/'source'/'narration.json').read_text())
DURATION=SCENES[-1]['end']
COUNT=len(SCENES)
FONT='/System/Library/Fonts/Supplemental/Arial.ttf'
BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'

def duration(file):
    r=subprocess.run([FF,'-hide_banner','-i',str(file)],capture_output=True,text=True)
    m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',r.stderr)
    h,m,s=map(float,m.groups())
    return h*3600+m*60+s

def stamp(seconds):
    ms=round(seconds*1000)
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'

def main():
    audio_inputs=[]
    audio_filters=[]
    durations=[]
    for i,s in enumerate(SCENES):
        voice=WORK/f'voice-{i}.aiff'
        length=duration(voice)
        slot=s['end']-s['start']-.6
        tempo=max(1,length/slot)
        durations.append({'chapter':i,'source_audio_seconds':length,'tempo':tempo})
        audio_inputs+=['-i',str(voice)]
        audio_filters.append(f'[{i}:a]atempo={tempo:.5f},aresample=48000,adelay={s["start"]*1000}|{s["start"]*1000}[a{i}]')
    audio_filters.append(''.join(f'[a{i}]' for i in range(COUNT))+f'amix=inputs={COUNT}:normalize=0,apad,atrim=duration={DURATION}[mix]')
    subprocess.run([FF,'-y','-hide_banner','-loglevel','warning',*audio_inputs,'-filter_complex',';'.join(audio_filters),'-map','[mix]','-c:a','pcm_s16le',str(WORK/'narration.wav')],check=True)
    srt=[]
    for i,s in enumerate(SCENES):
        im=Image.new('RGBA',(1600,900),(0,0,0,0))
        d=ImageDraw.Draw(im)
        navy='#102d3b'; teal='#42c9b5'; white='#f7fbfc'
        d.rectangle((0,0,1599,79),fill=navy)
        d.text((30,10),'MYSQL BROWSER FIDO GATEWAY  /  APPLICATION WALKTHROUGH',font=ImageFont.truetype(BOLD,12),fill='#a6c6cd')
        d.text((30,32),s['title'],font=ImageFont.truetype(BOLD,27),fill=white)
        d.rounded_rectangle((1350,19,1570,58),radius=10,fill='#244956')
        d.text((1374,30),'SIMULATED DEMO',font=ImageFont.truetype(BOLD,16),fill='#f2d198')
        d.rectangle((0,840,1599,899),fill=navy)
        d.rectangle((0,840,int(1600*s['end']/DURATION),843),fill=teal)
        d.text((30,850),s['caption'],font=ImageFont.truetype(BOLD,18),fill=white)
        d.text((30,876),'Actual app forms  •  Illustrated browser/device prompts  •  Simulated database and key',font=ImageFont.truetype(FONT,13),fill='#a6c6cd')
        d.text((1453,876),f'{i+1:02d} / {COUNT:02d}  ·  {DURATION//60}:{DURATION%60:02d}',font=ImageFont.truetype(FONT,13),fill='#a6c6cd')
        im.save(WORK/f'overlay-{i}.png')
        sentences=re.split(r'(?<=[.!?])\s+',s['voice'])
        weights=[len(sentence.split()) for sentence in sentences]
        speech_duration=min(durations[i]['source_audio_seconds']/durations[i]['tempo'],s['end']-s['start']-.2)
        cursor=s['start']
        for sentence,weight in zip(sentences,weights):
            end=cursor+speech_duration*weight/sum(weights)
            srt.append(f'{len(srt)+1}\n{stamp(cursor)} --> {stamp(end)}\n'+textwrap.fill(sentence,68)+'\n')
            cursor=end
    (OUT/'mysql-gateway-user-flow.srt').write_text('\n'.join(srt))
    inputs=['-i',str(WORK/'walkthrough.webm'),'-i',str(WORK/'narration.wav')]
    for i in range(COUNT): inputs+=['-loop','1','-framerate','25','-i',str(WORK/f'overlay-{i}.png')]
    filters=['[0:v]fps=25,pad=1600:900:0:80:color=0x102d3b[base]']
    previous='base'
    for i,s in enumerate(SCENES):
        current=f'v{i}'
        filters.append(f'[{previous}][{i+2}:v]overlay=0:0:enable=\'gte(t,{s["start"]})*lt(t,{s["end"]})\'[{current}]')
        previous=current
    filters.append(f'[{previous}]format=yuv420p,fade=t=in:st=0:d=0.3,fade=t=out:st={DURATION-.5}:d=0.5[video]')
    output=OUT/'mysql-gateway-user-flow.mp4'
    subprocess.run([FF,'-y','-hide_banner','-loglevel','warning',*inputs,'-filter_complex',';'.join(filters),'-map','[video]','-map','1:a','-c:v','libx264','-preset','fast','-crf','20','-c:a','aac','-b:a','160k','-t',str(DURATION),'-movflags','+faststart',str(output)],check=True)
    (OUT/'source'/'audio-timing.json').write_text(json.dumps(durations,indent=2))
    subprocess.run([FF,'-y','-hide_banner','-loglevel','warning','-ss',str(DURATION-6),'-i',str(output),'-frames:v','1','-update','1',str(OUT/'preview'/'final-login.png')],check=True)
    subprocess.run([FF,'-y','-hide_banner','-loglevel','warning','-ss','5','-i',str(output),'-frames:v','1',str(OUT/'preview'/'final-overview.png')],check=True)
    print(f'Created {output}; duration {duration(output)} seconds',flush=True)

if __name__=='__main__': main()
