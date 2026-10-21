# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Loopback-only controls and a PNG view of the original firmware's display."""
import json,queue,secrets,struct,threading,time,zlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

BUTTONS={'menu':67,'up':36,'down':37,'left':35,'right':34,'ok':74,'half':7,'i':72,'play':68}

def png_from_ppm(path):
 data=Path(path).read_bytes(); pos=0; tokens=[]
 while len(tokens)<4:
  while data[pos] in b' \t\r\n':pos+=1
  if data[pos]==35:pos=data.index(b'\n',pos)+1;continue
  end=pos
  while data[end] not in b' \t\r\n':end+=1
  tokens.append(data[pos:end]);pos=end
 magic,w,h,maximum=tokens;w=int(w);h=int(h)
 if magic!=b'P6' or maximum!=b'255':raise ValueError('Expected RGB8 PPM')
 pixels=data[pos+1:]
 if len(pixels)!=w*h*3:
  # QEMU's RGB24 pixman dump includes four-byte-aligned row padding.
  stride=(w*3+3)&~3
  if len(pixels)!=stride*h:raise ValueError('Unexpected PPM payload')
  pixels=b''.join(pixels[y*stride:y*stride+w*3] for y in range(h))
 def chunk(tag,payload):return struct.pack('>I',len(payload))+tag+payload+struct.pack('>I',zlib.crc32(tag+payload)&0xffffffff)
 scan=b''.join(b'\0'+pixels[y*w*3:(y+1)*w*3] for y in range(h))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan,3))+chunk(b'IEND',b'')

class Control:
 def __init__(self,port,*,playback=False,native_mcu=False,native_buttons=None,native_modes=False):
  self.native_mcu=bool(native_mcu);self.native_modes=bool(native_modes)
  self.allowed_buttons=set(BUTTONS if not native_mcu else native_buttons or [])
  self.playback=bool(playback)
  self.stop=threading.Event();self.queue=queue.Queue(maxsize=8);self.png=None;self.info={'state':'Booting original Z8 MAIN…'};self.token=secrets.token_hex(24)
  self.session=secrets.token_hex(12);self.ready=False;self.last_publish=None;self.submitted=0;self.sent=0;self.frame_version=0;self.shooting_mode="photo"
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def send(self,code,data,kind):
    self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
   def do_GET(self):
    route=self.path.split('?')[0]
    if route=='/':
     html=Path(__file__).with_name('control.html').read_text().replace('TOKEN_HERE',owner.token).replace('SESSION_HERE',owner.session)
     if owner.native_mcu:
      html=html.replace('Original MAIN 3.11 running locally.','Original MAIN 3.11 and EX03.00 running locally.').replace('Sensor imagery and external ROM data are simulated.','Sensor imagery and external ROM data are simulated. Original EX firmware supplies controller replies.')
      if not owner.status()['mode_available']:html=html.replace('Selector input; watch the camera display for the result.','Photo/Movie requires the experimental native Movie profile.')
     self.send(200,html.encode(),'text/html; charset=utf-8')
    elif route=='/frame.png' and owner.png:self.send(200,owner.png,'image/png')
    elif route=='/state':self.send(200,json.dumps(owner.status()).encode(),'application/json')
    elif route=='/control-session':self.send(200,json.dumps({'session':owner.session,'token':owner.token}).encode(),'application/json')
    else:self.send(404,b'Not ready','text/plain')
   def do_POST(self):
    if self.headers.get('X-Control-Token')!=owner.token:self.send(403,b'This emulator session changed. Reload the page.','text/plain');return
    button=self.path.removeprefix('/button/')
    if self.path=='/stop':owner.stop.set();self.send(200,b'{}','application/json')
    elif self.path in ('/mode/photo','/mode/movie'):
     if not owner.status()['mode_available']:self.send(409,b'Photo/Movie requires the experimental native Movie profile.','text/plain');return
     if not owner.status()['ready']:self.send(503,b'Camera controls are not ready.','text/plain');return
     try:
      owner.queue.put_nowait(('mode', self.path.rsplit('/',1)[1]));owner.submitted+=1
      self.send(202,json.dumps({'queued':owner.submitted}).encode(),'application/json')
     except queue.Full:self.send(429,b'Wait for previous input','text/plain')
    elif button in BUTTONS:
     if button not in owner.allowed_buttons:self.send(409,b'This control has no qualified native contact.','text/plain');return
     if button=='play' and not owner.playback:self.send(409,b'Playback requires a virtual card and playback model.','text/plain');return
     if not owner.status()['ready']:self.send(503,b'Camera controls are not ready. Check the status above the display.','text/plain');return
     try:
      owner.queue.put_nowait(("button", BUTTONS[button]));owner.submitted+=1
      self.send(202,json.dumps({'queued':owner.submitted}).encode(),'application/json')
     except queue.Full:self.send(429,b'Wait for previous input','text/plain')
    else:self.send(400,b'Unknown button','text/plain')
  self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler);self.server.daemon_threads=True
  threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def write_endpoint(self,out):
  target=Path(out)/'control-endpoint.json';temporary=target.with_suffix('.tmp')
  temporary.write_text(json.dumps({'url':f'http://127.0.0.1:{self.server.server_address[1]}/','session':self.session})+'\n');temporary.replace(target)
 def next_input(self):
  try:return self.queue.get_nowait()
  except queue.Empty:return None
 def mark_sent(self):self.sent+=1
 def status(self):
  stale=self.last_publish is not None and time.monotonic()-self.last_publish>5
  ready=self.ready and (not self.native_mcu or bool(self.allowed_buttons)) and not stale and not self.stop.is_set()
  info=dict(self.info,allowed_buttons=sorted(self.allowed_buttons),mode_available=not self.native_mcu or bool(self.native_modes and self.allowed_buttons),controller='native_ex' if self.native_mcu else 'host_peer',playback_available=self.playback,application='nikon-z8-emulator',session=self.session,ready=ready,submitted_inputs=self.submitted,sent_inputs=self.sent,queued_inputs=self.queue.qsize(),frame_version=self.frame_version,shooting_mode=self.shooting_mode)
  if self.stop.is_set():info['state']='Stopping emulator…'
  elif stale:info['state']='Emulator is not advancing. Controls paused.'
  return info
 def publish(self,path,row,ready=False):
  png=png_from_ppm(path)
  if png!=self.png:self.png=png;self.frame_version+=1
  self.ready=(self.ready or ready) and (not self.native_mcu or bool(self.allowed_buttons));self.last_publish=time.monotonic()
  self.info={'state':(('Running original MAIN/EX firmware' if self.ready else 'Original MAIN/EX running · camera inputs paused') if self.native_mcu and self.allowed_buttons else 'Original MAIN/EX running · display-only session' if self.native_mcu else 'Running original Z8 firmware' if self.ready else 'Starting camera display and menus…'),'virtual_seconds':round(row['virtual_seconds'],1),'display_frames':row['lcd']['frames'],'sensor_frames':row['raw']['frames']}
 def close(self):self.server.shutdown();self.server.server_close()
