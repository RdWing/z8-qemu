// SPDX-License-Identifier: GPL-2.0-or-later
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=Object.fromEntries(['state','screen','connection','input-status','shooting-mode','stop','playback-help'].map(id=>[id,{value:'photo',className:'',disabled:true}]));
const buttons=['menu','half','play'].map(key=>({dataset:{key},disabled:true})), calls=[], notifications=[];
let respond=async()=>({ok:true,status:202});
const context=vm.createContext({console,AbortSignal,setTimeout:()=>{},Date,
 document:{querySelector:s=>nodes[s.slice(1)],querySelectorAll:()=>buttons,activeElement:null},
 window:{webkit:{messageHandlers:{z8State:{postMessage:value=>notifications.push(value)}}}},
 fetch:async(path,options)=>{calls.push({path,options});return respond()}});
const source=fs.readFileSync(process.argv[2],'utf8').match(/<script>([\s\S]*?)<\/script>/)[1].replace(/poll\(\);\s*$/,'');
vm.runInContext(source,context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 assert.equal(Object.isFrozen(context.window.z8Workbench),true);
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
})().catch(error=>{console.error(error);process.exitCode=1});
