# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Loopback-only controls and a PNG view of the original firmware's display."""
import json,queue,secrets,struct,threading,time,zlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

BUTTONS={'menu':67,'up':36,'down':37,'left':35,'right':34,'ok':74,'half':7,'i':72}

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
 def __init__(self,port):
  self.stop=threading.Event();self.queue=queue.Queue(maxsize=8);self.png=None;self.info={'state':'Booting original Z8 MAIN…'};self.token=secrets.token_hex(24)
  self.session=secrets.token_hex(12);self.ready=False;self.last_publish=None;self.submitted=0;self.sent=0;self.frame_version=0
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def send(self,code,data,kind):
    self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
   def do_GET(self):
    route=self.path.split('?')[0]
    if route=='/':self.send(200,(Path(__file__).with_name('control.html').read_text().replace('TOKEN_HERE',owner.token).replace('SESSION_HERE',owner.session)).encode(),'text/html; charset=utf-8')
    elif route=='/frame.png' and owner.png:self.send(200,owner.png,'image/png')
    elif route=='/state':self.send(200,json.dumps(owner.status()).encode(),'application/json')
    elif route=='/control-session':self.send(200,json.dumps({'session':owner.session,'token':owner.token}).encode(),'application/json')
    else:self.send(404,b'Not ready','text/plain')
   def do_POST(self):
    if self.headers.get('X-Control-Token')!=owner.token:self.send(403,b'This emulator session changed. Reload the page.','text/plain');return
    button=self.path.removeprefix('/button/')
    if self.path=='/stop':owner.stop.set();self.send(200,b'{}','application/json')
    elif button in BUTTONS:
     if not owner.status()['ready']:self.send(503,b'Camera controls are not ready. Check the status above the display.','text/plain');return
     try:
      owner.queue.put_nowait(BUTTONS[button]);owner.submitted+=1
      self.send(202,json.dumps({'queued':owner.submitted}).encode(),'application/json')
     except queue.Full:self.send(429,b'Wait for previous input','text/plain')
    else:self.send(400,b'Unknown button','text/plain')
  self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler);self.server.daemon_threads=True
  threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def next_button(self):
  try:return self.queue.get_nowait()
  except queue.Empty:return None
 def mark_sent(self):self.sent+=1
 def status(self):
  stale=self.last_publish is not None and time.monotonic()-self.last_publish>5
  ready=self.ready and not stale and not self.stop.is_set()
  info=dict(self.info,application='nikon-z8-emulator',session=self.session,ready=ready,submitted_inputs=self.submitted,sent_inputs=self.sent,queued_inputs=self.queue.qsize(),frame_version=self.frame_version)
  if self.stop.is_set():info['state']='Stopping emulator…'
  elif stale:info['state']='Emulator is not advancing. Controls paused.'
  return info
 def publish(self,path,row,ready=False):
  png=png_from_ppm(path)
  if png!=self.png:self.png=png;self.frame_version+=1
  self.ready=self.ready or ready;self.last_publish=time.monotonic()
  self.info={'state':'Running original Z8 firmware' if self.ready else 'Starting camera display and menus…','virtual_seconds':round(row['virtual_seconds'],1),'display_frames':row['lcd']['frames'],'sensor_frames':row['raw']['frames']}
 def close(self):self.server.shutdown();self.server.server_close()
