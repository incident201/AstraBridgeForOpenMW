import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp, readFile, rm, utimes, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {withInstallationLock} from '../main/installation-lock';

test('installation mutex excludes concurrent operations and releases after an error', async()=>{
  const directory = await mkdtemp(join(tmpdir(), 'astra-lock-'));
  const config = join(directory, 'installation.json');
  let started!:()=>void, finish!:()=>void;
  const entered = new Promise<void>(resolve => started = resolve);
  const done = new Promise<void>(resolve => finish = resolve);
  const running = withInstallationLock(config, async()=>{started();await done;});
  try {
    await entered;
    await assert.rejects(()=>withInstallationLock(config, async()=>{}), /management operation is running/);
    finish();await running;
    await assert.rejects(()=>withInstallationLock(config, async()=>{throw Error('fixture failure');}), /fixture failure/);
    assert.equal(await withInstallationLock(config, async()=>42), 42);
  } finally {
    finish();await running;
    await rm(directory, {recursive:true, force:true});
  }
});

test('abandoned locks recover even if their old PID is reused or cannot be probed', async t=>{
  const directory = await mkdtemp(join(tmpdir(), 'astra-lock-stale-'));
  const config = join(directory, 'installation.json');
  try {
    await writeFile(config + '.lock', JSON.stringify({version:2, pid:process.pid}));
    const probe = t.mock.method(process, 'kill', ()=>{throw Object.assign(Error('permission denied'), {code:'EPERM'});});
    assert.equal(await withInstallationLock(config, async()=>true), true);
    assert.equal(probe.mock.callCount(), 0);
  } finally {
    t.mock.restoreAll();
    await rm(directory, {recursive:true, force:true});
  }
});

test('empty and malformed legacy lock files recover without manual removal', async()=>{
  const directory = await mkdtemp(join(tmpdir(), 'astra-lock-invalid-'));
  const config = join(directory, 'installation.json');
  try {
    for (const source of ['', '{truncated', 'null', '{"pid":"unexpected"}']) {
      await writeFile(config + '.lock', source);
      assert.equal(await withInstallationLock(config, async()=>true), true);
      await assert.rejects(readFile(config + '.lock'), {code:'ENOENT'});
    }
  } finally {await rm(directory, {recursive:true, force:true});}
});

test('a live legacy installer is preserved, including an EPERM process probe', async t=>{
  const directory = await mkdtemp(join(tmpdir(), 'astra-lock-legacy-'));
  const config = join(directory, 'installation.json');
  try {
    const source = JSON.stringify({pid:process.pid});
    await writeFile(config + '.lock', source);
    await assert.rejects(()=>withInstallationLock(config, async()=>{}), /management operation is running/);
    t.mock.method(process, 'kill', ()=>{throw Object.assign(Error('permission denied'), {code:'EPERM'});});
    await assert.rejects(()=>withInstallationLock(config, async()=>{}), /management operation is running/);
    assert.equal(await readFile(config + '.lock', 'utf8'), source);
  } finally {
    t.mock.restoreAll();
    await rm(directory, {recursive:true, force:true});
  }
});

test('an old PID-only lock is reclaimed when the PID now belongs to a newer process', async t=>{
  const directory = await mkdtemp(join(tmpdir(), 'astra-lock-reused-'));
  const config = join(directory, 'installation.json');
  try {
    await writeFile(config + '.lock', JSON.stringify({pid:process.pid}));
    const beforeThisProcess = new Date('2000-01-01T00:00:00Z');
    await utimes(config + '.lock', beforeThisProcess, beforeThisProcess);
    const probe = t.mock.method(process, 'kill', ()=>{throw Object.assign(Error('permission denied'), {code:'EPERM'});});
    assert.equal(await withInstallationLock(config, async()=>true), true);
    assert.equal(probe.mock.callCount(), 0);
  } finally {
    t.mock.restoreAll();
    await rm(directory, {recursive:true, force:true});
  }
});

test('a killed installer releases its OS mutex and its surviving PID file is recovered', async()=>{
  const directory = await mkdtemp(join(tmpdir(), 'astra-lock-crash-'));
  const config = join(directory, 'installation.json');
  const helper = new URL('../main/installation-lock.ts', import.meta.url).href;
  const child = spawn(process.execPath, ['--import', 'tsx', '--input-type=module', '-e',
    `import {withInstallationLock} from ${JSON.stringify(helper)};
     await withInstallationLock(process.argv[1], async()=>{
       process.stdout.write('ready'); await new Promise(()=>{});
     });`, config], {stdio:['ignore', 'pipe', 'pipe']});
  let diagnostics = '';
  child.stderr.setEncoding('utf8');child.stderr.on('data', chunk=>diagnostics += chunk);
  try {
    await new Promise<void>((resolve, reject)=>{
      child.stdout.once('data', ()=>resolve());
      child.once('error', reject);
      child.once('exit', ()=>reject(Error(diagnostics || 'Fixture exited before holding its mutex')));
    });
    await assert.rejects(()=>withInstallationLock(config, async()=>{}), /management operation is running/);
    const exited = once(child, 'exit');child.kill('SIGKILL');await exited;
    assert.equal(JSON.parse(await readFile(config + '.lock', 'utf8')).version, 2);
    assert.equal(await withInstallationLock(config, async()=>true), true);
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await rm(directory, {recursive:true, force:true});
  }
});
