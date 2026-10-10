import {spawn, type ChildProcess} from 'node:child_process';
import {readdir, readFile} from 'node:fs/promises';

interface ProcessIdentity {pid:number;group:number;started:string;state:string}

async function identity(pid:number):Promise<ProcessIdentity|null> {
  try {
    const source = await readFile(`/proc/${pid}/stat`, 'utf8');
    const fields = source.slice(source.lastIndexOf(') ') + 2).trim().split(/\s+/);
    return {pid, state:fields[0], group:Number(fields[2]), started:fields[19]};
  } catch (error) {
    if (['ENOENT', 'ESRCH'].includes((error as NodeJS.ErrnoException).code ?? '')) return null;
    throw error;
  }
}

async function descendants(pid:number):Promise<ProcessIdentity[]> {
  const process = await identity(pid);
  if (!process) return [];
  let threads:string[];
  try {
    threads = await readdir(`/proc/${pid}/task`);
  } catch (error) {
    if (['ENOENT', 'ESRCH'].includes((error as NodeJS.ErrnoException).code ?? '')) return [process];
    throw error;
  }
  // Go-based Podman may fork helpers from a thread other than its main thread.
  const children = await Promise.all(threads.map(async thread => {
    try {
      return await readFile(`/proc/${pid}/task/${thread}/children`, 'utf8');
    } catch (error) {
      if (['ENOENT', 'ESRCH'].includes((error as NodeJS.ErrnoException).code ?? '')) return '';
      throw error;
    }
  }));
  const childPids = new Set(children.flatMap(source => source.trim().split(/\s+/).filter(Boolean).map(Number)));
  const nested = await Promise.all([...childPids].map(descendants));
  return [...nested.flat(), process];
}

function signalGroup(group:number, signal:NodeJS.Signals):void {
  try {
    process.kill(-group, signal);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
  }
}

async function alive(original:ProcessIdentity):Promise<boolean> {
  const current = await identity(original.pid);
  return Boolean(current && current.started === original.started && !['Z', 'X'].includes(current.state));
}

/** script's PTY child has a separate session: killing only script's group is insufficient. */
export async function terminateProcessTree(child:ChildProcess):Promise<void> {
  if (!child.pid) return;
  if (process.platform === 'win32') {
    await new Promise<void>((resolve, reject) => {
      const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {stdio:'ignore', windowsHide:true});
      const timer = setTimeout(() => {
        killer.kill();
        child.kill();
        reject(new Error('Timed out terminating the runtime process tree'));
      }, 5000);
      killer.once('error', error => {
        clearTimeout(timer);
        child.kill();
        reject(error);
      });
      killer.once('close', code => {
        clearTimeout(timer);
        if (code !== 0 && child.exitCode === null && child.signalCode === null) {
          child.kill();
          reject(new Error('Unable to terminate the runtime process tree'));
        } else resolve();
      });
    });
    return;
  }
  const processes = process.platform === 'linux' ? await descendants(child.pid) : [];
  const groups = new Set([...processes.map(value => value.group), child.pid]);
  for (const group of groups) signalGroup(group, 'SIGTERM');
  // Allow a normal exit, then kill stubborn PTY descendants before settling.
  const deadline = Date.now() + 1000;
  let remaining = processes;
  while (remaining.length && Date.now() < deadline) {
    const living = await Promise.all(remaining.map(alive));
    remaining = remaining.filter((_, index) => living[index]);
    if (remaining.length) await new Promise(resolve => setTimeout(resolve, 25));
  }
  for (const group of new Set(remaining.map(value => value.group))) signalGroup(group, 'SIGKILL');
  if (process.platform !== 'linux') signalGroup(child.pid, 'SIGKILL');
}
