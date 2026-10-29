# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Loopback-only controls and a PNG view of the original firmware's display."""
import json,queue,secrets,struct,threading,time,zlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import panel

BUTTONS={'menu':67,'up':36,'down':37,'left':35,'right':34,'ok':74,'half':7,'i':72,'play':68,'disp':83,'protect':73,'delete':69}

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
 def __init__(self,port,*,playback=False,native_mcu=False,native_buttons=None,native_modes=False,native_capture=False,native_dials=False,native_supply=False,native_wake=False):
  self.native_mcu=bool(native_mcu);self.native_modes=bool(native_modes);self.powered_down=False;self.cancelled=0;self.native_supply=bool(native_mcu and native_supply);self.supply_resets=0
  self.allowed_buttons=set(set(BUTTONS)-{'disp','protect','delete'} if not native_mcu else native_buttons or [])
  self.native_dials=bool(native_mcu and native_dials)
  self.playback=bool(playback)
  self.native_capture=bool(native_mcu and native_capture);self.capture_ready=False;self.capture_retired=False;self.capture_busy=False
  self.capture_serial=0;self.capture_finished=0;self.capture_error=None;self.capture_completed_jobs=0
  self.native_wake=bool(self.native_supply and native_wake);self.supply_off=False
  self.wake_requested=False;self.wake_busy=False;self.wake_error=None
  self.input_lock=threading.RLock()
  self.stop=threading.Event();self.queue=queue.Queue(maxsize=8);self.png=None;self.info={'state':'Booting original Z8 MAIN…'};self.token=secrets.token_hex(24)
  self.session=secrets.token_hex(12);self.ready=False;self.last_publish=None;self.submitted=0;self.sent=0;self.frame_version=0;self.shooting_mode="photo";self.panel_png=None;self.panel_info={};self.panel_version=0
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
     if not owner.status()['mode_available']:
      mode_help='Use a Movie session for Photo/Movie live view.' if owner.native_capture else 'Photo/Movie requires the experimental native Movie profile.'
      html=html.replace('Selector input; watch the camera display for the result.',mode_help)
     self.send(200,html.encode(),'text/html; charset=utf-8')
    elif route=='/frame.png' and owner.png:self.send(200,owner.png,'image/png')
    elif route=='/panel.png' and owner.native_mcu and owner.panel_png:self.send(200,owner.panel_png,'image/png')
    elif route=='/state':self.send(200,json.dumps(owner.status()).encode(),'application/json')
    elif route=='/control-session':self.send(200,json.dumps({'session':owner.session,'token':owner.token}).encode(),'application/json')
    else:self.send(404,b'Not ready','text/plain')
   def do_POST(self):
    with owner.input_lock:self.handle_post()
   def handle_post(self):
    if self.headers.get('X-Control-Token')!=owner.token:self.send(403,b'This emulator session changed. Reload the page.','text/plain');return
    button=self.path.removeprefix('/button/')
    if self.path=='/stop':owner.stop.set();self.send(200,b'{}','application/json')
    elif self.path=='/wake':
     if not owner.native_wake:self.send(409,b'Wake requires the explicit MAIN supply fixture.','text/plain');return
     if owner.wake_busy:self.send(409,b'Wake is already in progress.','text/plain');return
     if not owner.status()['wake_ready']:self.send(503,b'Camera is not ready for wake.','text/plain');return
     owner.wake_requested=True;owner.wake_busy=True;owner.wake_error=None;owner.submitted+=1
     self.send(202,b'{}','application/json')
    elif self.path=='/capture':
     with owner.input_lock:
      if not owner.native_capture:self.send(409,b'Capture requires the experimental native HE profile and virtual card.','text/plain');return
      if owner.capture_busy:self.send(409,b'Capture is already in progress.','text/plain');return
      if not owner.status()['capture_ready']:self.send(503,b'Capture controls are not ready. Check the camera display.','text/plain');return
      try:owner.queue.put_nowait(('capture',None))
      except queue.Full:self.send(429,b'Wait for previous input','text/plain');return
      owner.capture_busy=True;owner.capture_serial+=1;owner.capture_error=None;owner.submitted+=1
      self.send(202,json.dumps({'capture_id':owner.capture_serial}).encode(),'application/json')
    elif self.path.startswith('/dial/'):
     pieces=self.path.split('/')
     if len(pieces)!=4 or pieces[2] not in ('main','sub','mode','compensation') or pieces[3] not in ('-1','1'):
      self.send(400,b'Expected main/sub/mode/compensation dial and direction -1 or 1.','text/plain');return
     if not owner.status()['dials_available']:self.send(409,b'Dials require native EX controls.','text/plain');return
     if owner.capture_busy:self.send(409,b'Wait for capture to finish.','text/plain');return
     if not owner.status()['ready']:self.send(503,b'Camera controls are not ready.','text/plain');return
     try:
      owner.queue.put_nowait((pieces[2]+'-dial',int(pieces[3])) if pieces[2] in ('mode','compensation') else ('dial',(pieces[2],int(pieces[3]))));owner.submitted+=1
      self.send(202,json.dumps({'queued':owner.submitted}).encode(),'application/json')
     except queue.Full:self.send(429,b'Wait for previous input','text/plain')
    elif self.path in ('/mode/photo','/mode/movie'):
     if owner.capture_busy:self.send(409,b'Wait for capture to finish.','text/plain');return
     if not owner.status()['mode_available']:self.send(409,b'Photo/Movie requires the experimental native Movie profile.','text/plain');return
     if not owner.status()['ready']:self.send(503,b'Camera controls are not ready.','text/plain');return
     try:
      owner.queue.put_nowait(('mode', self.path.rsplit('/',1)[1]));owner.submitted+=1
      self.send(202,json.dumps({'queued':owner.submitted}).encode(),'application/json')
     except queue.Full:self.send(429,b'Wait for previous input','text/plain')
    elif button in BUTTONS:
     if owner.capture_busy:self.send(409,b'Wait for capture to finish.','text/plain');return
     if button not in owner.allowed_buttons:self.send(409,b'This control has no qualified native contact.','text/plain');return
     if button in ('play','protect','delete') and not owner.playback:self.send(409,b'Review controls require a virtual card and playback model.','text/plain');return
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
  if self.wake_requested:
   self.wake_requested=False;return ('wake',None)
  if self.powered_down:return None
  try:return self.queue.get_nowait()
  except queue.Empty:return None
 def mark_sent(self):self.sent+=1
 def finish_capture(self,error=None):
  with self.input_lock:
   self.capture_finished=self.capture_serial;self.capture_busy=False;self.capture_error=error
 def finish_wake(self,error=None):
  with self.input_lock:
   self.wake_requested=False;self.wake_busy=False;self.wake_error=error
 def status(self):
  stale=self.last_publish is not None and time.monotonic()-self.last_publish>5
  ready=self.ready and (not self.native_mcu or bool(self.allowed_buttons)) and not stale and not self.stop.is_set() and not self.wake_busy
  info=dict(self.info,powered_down=self.powered_down,cancelled_inputs=self.cancelled,allowed_buttons=sorted(self.allowed_buttons),mode_available=not self.native_mcu or bool(self.native_modes and self.allowed_buttons),controller='native_ex' if self.native_mcu else 'host_peer',playback_available=self.playback,application='nikon-z8-emulator',session=self.session,ready=ready,submitted_inputs=self.submitted,sent_inputs=self.sent,queued_inputs=self.queue.qsize(),frame_version=self.frame_version,shooting_mode=self.shooting_mode)
  info['dials_available']=bool(self.native_dials and self.allowed_buttons)
  info.update(panel_available=bool(self.native_mcu and self.panel_png),panel_version=self.panel_version,
              panel_display_on=self.panel_info.get('display_on',False),panel_lines=self.panel_info.get('lines',0),panel_packets=self.panel_info.get('packets',0))
  info.update(capture_available=self.native_capture,capture_busy=self.capture_busy,
              capture_ready=bool(self.native_capture and ready and self.capture_ready and not self.capture_busy and not self.queue.qsize() and self.shooting_mode=='photo'),
              capture_serial=self.capture_serial,capture_finished=self.capture_finished,capture_error=self.capture_error)
  info.update(wake_available=self.native_wake,wake_busy=self.wake_busy,wake_error=self.wake_error,
              wake_ready=bool(self.native_wake and self.powered_down and self.supply_off and
                  not stale and self.last_publish is not None and not self.stop.is_set() and
                  not self.capture_busy and not self.wake_busy))
  if self.wake_busy:info['state']='Waking camera…'
  if self.capture_busy and not self.powered_down:
   info['ready']=False;info['state']='Capturing photo…'
  if self.stop.is_set():info['state']='Stopping emulator…'
  elif stale:info['state']='Emulator is not advancing. Controls paused.'
  return info
 def publish_panel(self,bits,metadata):
  if not self.native_mcu:raise ValueError('Panel observation requires native EX')
  if metadata.get('enabled') is not True or metadata.get('width')!=panel.WIDTH or metadata.get('height')!=panel.HEIGHT:
   raise ValueError('Expected the bounded native panel model')
  image=panel.png(bits,metadata.get('display_on'))
  if image!=self.panel_png:self.panel_png=image;self.panel_version+=1
  self.panel_info=dict(metadata)
 def publish(self,path,row,ready=False):
  png=png_from_ppm(path)
  if png!=self.png:self.png=png;self.frame_version+=1
  supply=row.get('main_supply',{}) if self.native_supply else {}
  self.supply_off=bool(supply.get('enabled') and supply.get('off'))
  resets=int(supply.get('resets',0))
  restarted=bool(supply.get('enabled') and not supply.get('off') and resets>self.supply_resets)
  self.supply_resets=max(self.supply_resets,resets)
  if restarted:self.powered_down=False;self.ready=False
  self.powered_down=self.powered_down or bool(row.get('powered_down')) or bool(supply.get('off'))
  if self.powered_down:
   while not self.queue.empty():
    try:self.queue.get_nowait();self.cancelled+=1
    except queue.Empty:break
  self.capture_ready=bool(row.get('capture_ready'))
  self.capture_retired=bool(row.get('capture_retired'))
  self.capture_completed_jobs=int(row.get('capture_completed_jobs',0))
  self.ready=(self.ready or ready) and not row.get('preparing_capture',False) and not self.powered_down and (not self.native_mcu or bool(self.allowed_buttons));self.last_publish=time.monotonic()
  self.info={'state':(('Running original MAIN/EX firmware' if self.ready else 'Original MAIN/EX running · camera inputs paused') if self.native_mcu and self.allowed_buttons else 'Original MAIN/EX running · display-only session' if self.native_mcu else 'Running original Z8 firmware' if self.ready else 'Starting camera display and menus…'),'virtual_seconds':round(row['virtual_seconds'],1),'display_frames':row['lcd']['frames'],'sensor_frames':row['raw']['frames']}
  if row.get('preparing_capture'):self.info['state']='Preparing experimental capture controls…'
  if self.powered_down:self.info['state']=('Camera is powered down. Wake camera to continue.' if self.native_wake and self.supply_off else 'Camera firmware entered power-down. Restart the session to continue.')
 def close(self):self.server.shutdown();self.server.server_close()
