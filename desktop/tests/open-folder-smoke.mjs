/** Run with a disposable configuration, a display and a logging xdg-open fixture. */
import {_electron as electron,expect} from '@playwright/test';
import {readFile,mkdir} from 'node:fs/promises';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const executable=process.env.ASTRA_DESKTOP_EXECUTABLE,config=process.env.ASTRA_CONFIG;
const output=process.env.ASTRA_TEST_OUTPUT,openLog=process.env.ASTRA_OPEN_LOG;
if(!executable||!config||!output||!openLog)throw Error('Set ASTRA_DESKTOP_EXECUTABLE, ASTRA_CONFIG, ASTRA_TEST_OUTPUT and ASTRA_OPEN_LOG');
await mkdir(output,{recursive:true});
const directory=JSON.parse(await readFile(config,'utf8')).recordingsDirectory;
const env={...process.env,ASTRA_CONFIG:resolve(config),ASTRA_DESKTOP_DATA:join(resolve(output),'userdata'),APPDIR:dirname(resolve(executable))};
delete env.ELECTRON_RUN_AS_NODE;delete env.ASTRA_RESOURCES;
const app=await electron.launch({executablePath:resolve(executable),args:['--no-sandbox','--ozone-platform=x11','--js-flags=--expose-gc'],env});
try{
  const page=await app.firstWindow();
  await page.waitForFunction(()=>window.astra);
  const state=await page.evaluate(()=>window.astra.invoke('status'));
  assert.equal(state.container.running,false,'Use a stopped disposable installation');
  await app.evaluate(()=>{globalThis.folderTestGC=setInterval(()=>globalThis.gc?.(),100);});
  const calls=async()=>(await readFile(openLog,'utf8').catch(()=>'')).trim().split('\n').filter(Boolean);
  const before=(await calls()).length;
  const opened=await page.evaluate(()=>window.astra.invoke('open-recordings-folder'));
  assert.equal(opened,directory,'The real IPC handler must complete normally');
  await expect.poll(calls).toHaveLength(before+1);
  await page.getByRole('navigation').getByRole('button',{name:'Recordings',exact:true}).click();
  await page.getByRole('button',{name:'Open folder',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.session-menu button')?.disabled);
  await page.getByRole('navigation').getByRole('button',{name:'Setup',exact:true}).click();
  await page.getByRole('button',{name:'Storage and skill',exact:true}).click();
  await page.getByRole('button',{name:'Open recordings folder',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.session-menu button')?.disabled);
  assert.equal(await page.getByRole('alert').count(),0,'No false error after opening the folder');
  await expect.poll(calls).toHaveLength(before+3);
  const after=await calls();
  for(const url of after.slice(-3))assert.equal(fileURLToPath(url),directory);
  assert.equal((await page.evaluate(()=>window.astra.invoke('status'))).container.running,false);
  await page.screenshot({path:join(output,'folder-opened.png')});
  console.log('Packaged Desktop: IPC completed and both folder buttons opened the exact directory without an error or container start.');
}finally{await app.close();}
