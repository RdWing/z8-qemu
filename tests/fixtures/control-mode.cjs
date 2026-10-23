// SPDX-License-Identifier: GPL-2.0-or-later
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=Object.fromEntries(['state','screen','connection','input-status','shooting-mode','stop','playback-help','capture','capture-help','display-help','ex-panel','panel-screen','panel-status','dial-help'].map(id=>[id,{value:'photo',className:'',disabled:true}]));
const buttons=['menu','half','play','i','disp','protect','delete'].map(key=>({dataset:{key},disabled:true})), calls=[], notifications=[];
const dials=['main','sub','mode','compensation'].flatMap(dial=>[-1,1].map(direction=>({dataset:{dial,direction:String(direction)},disabled:true})));
let respond=async()=>({ok:true,status:202});
const context=vm.createContext({console,AbortSignal,setTimeout:()=>{},Date,
 document:{querySelector:s=>nodes[s.slice(1)],querySelectorAll:s=>s==='[data-dial]'?dials:buttons,activeElement:null},
 window:{webkit:{messageHandlers:{z8State:{postMessage:value=>notifications.push(value)}}}},
 fetch:async(path,options)=>{calls.push({path,options});return respond()}});
const source=fs.readFileSync(process.argv[2],'utf8').match(/<script>([\s\S]*?)<\/script>/)[1].replace(/poll\(\);\s*$/,'');
vm.runInContext(source,context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 assert.equal(Object.isFrozen(context.window.z8Workbench),true);
 await run("window.z8Workbench.press('menu')");assert.equal(calls.length,0);
 run("allowedButtons=['menu','half','play'];playback=false;available(true)");
 assert.deepEqual(Array.from(notifications.at(-1).buttonsReady),['menu','half']);
 await run("window.z8Workbench.press('play')");await run("window.z8Workbench.press('i')");
 await run("window.z8Workbench.press('../stop')");assert.equal(calls.length,0);
 run("playback=true;available(true)");
 assert.deepEqual(Array.from(notifications.at(-1).buttonsReady),['menu','half','play']);
 await run("window.z8Workbench.press('play')");assert.equal(calls.at(-1).path,'/button/play');
 assert.equal(calls.at(-1).options.headers['X-Control-Token'],'TOKEN_HERE');calls.length=0;
 run("allowedButtons.push('disp');available(true)");
 assert.equal(buttons.find(b=>b.dataset.key==='disp').disabled,false);
 await run("window.z8Workbench.press('disp')");assert.equal(calls.at(-1).path,'/button/disp');
 run("allowedButtons.push('protect','delete');playback=false;available(true)");
 for(const key of ['protect','delete']) {
  assert.equal(buttons.find(b=>b.dataset.key===key).disabled,true);
  const before=calls.length;await run(`window.z8Workbench.press('${key}')`);assert.equal(calls.length,before);
 }
 run('playback=true;available(true)');
 for(const key of ['protect','delete']) {
  assert.equal(buttons.find(b=>b.dataset.key===key).disabled,false);
  await run(`window.z8Workbench.press('${key}')`);assert.equal(calls.at(-1).path,'/button/'+key);
 }
 const beforeDeleteShortcut=calls.length;
 for(const key of ['Delete','Backspace'])context.document.onkeydown({key,target:{tagName:'BODY'}});
 assert.equal(calls.length,beforeDeleteShortcut);
 const beforeShortcut=calls.length;
 context.document.onkeydown({key:'d',target:{tagName:'BODY'},metaKey:true});
 assert.equal(calls.length,beforeShortcut);
 calls.length=0;
 assert.equal(await run("window.z8Workbench.turnDial('main',1)"),false);
 run('dialsAvailable=true;available(true)');
 assert.equal(notifications.at(-1).dialsReady,true);assert.equal(dials.every(b=>!b.disabled),true);
 for(const axis of ['main','sub','mode','compensation'])for(const sign of [-1,1]) {
  assert.equal(await run(`window.z8Workbench.turnDial('${axis}',${sign})`),true);
  assert.equal(calls.at(-1).path,`/dial/${axis}/${sign}`);
 }
 const beforeInvalidDial=calls.length;
 for(const command of ["turnDial('../stop',1)","turnDial('main',0)","turnDial('main',true)","turnDial('main',127)"])
  assert.equal(await run('window.z8Workbench.'+command),false);
 assert.equal(calls.length,beforeInvalidDial);calls.length=0;
 run('available(false)');assert.deepEqual(Array.from(notifications.at(-1).buttonsReady),[]);
 assert.equal(await run("window.z8Workbench.selectMode('movie')"),false);
 run('modeAvailable=false;available(true)');
 assert.equal(await run("window.z8Workbench.selectMode('movie')"),false);
 run('modeAvailable=true;available(true)');
 assert.equal(notifications.at(-1).modeReady,true);
 assert.equal(await run("window.z8Workbench.selectMode('../stop')"),false);
 assert.equal(calls.length,0);
 let release;
 respond=()=>new Promise(resolve=>{release=resolve});
 const pending=run("window.z8Workbench.selectMode('movie')");
 assert.equal(nodes['shooting-mode'].disabled,true);
 assert.equal(notifications.at(-1).modeReady,false);
 assert.equal(await run("window.z8Workbench.selectMode('photo')"),false);
 assert.equal(calls.length,1);
 assert.equal(calls[0].path,'/mode/movie');
 assert.equal(calls[0].options.method,'POST');
 assert.equal(calls[0].options.headers['X-Control-Token'],'TOKEN_HERE');
 release({ok:true,status:202});assert.equal(await pending,true);
 assert.equal(nodes['shooting-mode'].value,'movie');
 assert.equal(nodes['shooting-mode'].disabled,false);
 assert.equal(notifications.at(-1).modeReady,true);
 respond=async()=>({ok:false,status:403,text:async()=> 'Session changed'});
 assert.equal(await run("window.z8Workbench.selectMode('photo')"),false);
 assert.equal(nodes['shooting-mode'].disabled,true);
 assert.equal(notifications.at(-1).modeReady,false);
 assert.equal(await run("window.z8Workbench.selectMode('movie')"),false);
 assert.equal(calls.length,2);
 assert.match(nodes.connection.textContent,/restarted/);
 run('captureAvailable=true;captureCanRun=true;captureWaiting=0;available(true)');
 assert.equal(nodes.capture.disabled,false);
 let finishCapture;
 respond=()=>new Promise(resolve=>{finishCapture=resolve});
 const capture=run('window.z8Workbench.capturePhoto()');
 assert.equal(nodes.capture.disabled,true);
 assert.deepEqual(Array.from(notifications.at(-1).buttonsReady),[]);
 const beforeDial=calls.length;assert.equal(await run("window.z8Workbench.turnDial('main',1)"),false);assert.equal(calls.length,beforeDial);
 const beforeButton=calls.length;await run("window.z8Workbench.press('menu')");assert.equal(calls.length,beforeButton);
 assert.equal(await run('window.z8Workbench.capturePhoto()'),false);
 assert.equal(calls.at(-1).path,'/capture');
 finishCapture({ok:true,status:202,json:async()=>({capture_id:7})});
 assert.equal(await capture,true);assert.equal(nodes.capture.disabled,true);
 respond=async()=>({ok:true,json:async()=>({session:'SESSION_HERE',capture_available:true,
  capture_ready:true,capture_finished:7,ready:true,allowed_buttons:['menu','half','play'],
  mode_available:false,playback_available:false})});
 await run('poll()');assert.equal(nodes.capture.disabled,false);assert.equal(nodes['ex-panel'].hidden,true);
 assert.equal(notifications.at(-1).captureReady,true);
 assert.equal(notifications.at(-1).modeReady,false);assert.equal(nodes['shooting-mode'].disabled,true);
 respond=async()=>({ok:true,json:async()=>({session:'SESSION_HERE',panel_available:true,
  panel_version:2,panel_display_on:true,panel_lines:128,panel_packets:9})});
 await run('poll()');assert.equal(nodes['ex-panel'].hidden,false);
 assert.equal(nodes['panel-screen'].src,'/panel.png?v=2');
 assert.match(nodes['panel-status'].textContent,/128 lines/);
 respond=async()=>({ok:true,json:async()=>({session:'SESSION_HERE',panel_available:true,
  panel_version:3,panel_display_on:false,panel_lines:128,panel_packets:9})});
 await run('poll()');assert.match(nodes['panel-status'].textContent,/Display off/);
 run('disconnected()');assert.equal(nodes['panel-screen'].src,'/panel.png?v=3');
 respond=async()=>({ok:false,status:403,text:async()=> 'Session changed'});
 assert.equal(await run('window.z8Workbench.capturePhoto()'),false);
 assert.equal(nodes.capture.disabled,true);assert.equal(notifications.at(-1).captureReady,false);

})().catch(error=>{console.error(error);process.exitCode=1});
