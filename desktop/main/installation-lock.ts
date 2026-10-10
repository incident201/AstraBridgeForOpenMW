import {createHash} from 'node:crypto';
import {execFile} from 'node:child_process';
import {mkdir, readFile, realpath, rm, stat, writeFile} from 'node:fs/promises';
import {createServer, type Server} from 'node:net';
import {basename, dirname, join, resolve} from 'node:path';
import {promisify} from 'node:util';

const busyMessage = 'Another installation management operation is running';
const execute = promisify(execFile);

async function processCreatedAt(pid:number):Promise<number|null> {
  try {
    if (process.platform === 'win32') {
      const command = `[DateTimeOffset]::new((Get-Process -Id ${pid} -ErrorAction Stop).StartTime.ToUniversalTime()).ToUnixTimeMilliseconds()`;
      const {stdout} = await execute('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
        {encoding:'utf8', windowsHide:true, timeout:2000, maxBuffer:4096});
      const created = Number(stdout.trim());
      return Number.isFinite(created) && created > 0 ? created : null;
    }
    if (process.platform === 'linux') {
      const [source, system, ticks] = await Promise.all([
        readFile(`/proc/${pid}/stat`, 'utf8'), readFile('/proc/stat', 'utf8'),
        execute('getconf', ['CLK_TCK'], {encoding:'utf8', timeout:2000, maxBuffer:4096}),
      ]);
      const fields = source.slice(source.lastIndexOf(') ') + 2).trim().split(/\s+/);
      const boot = Number(/^btime (\d+)$/m.exec(system)?.[1]);
      const frequency = Number(ticks.stdout.trim());
      const started = Number(fields[19]);
      return Number.isFinite(boot) && Number.isFinite(started) && frequency > 0
        ? (boot + started / frequency) * 1000 : null;
    }
  } catch {
    // An unavailable identity probe is not proof that an old installer is dead.
  }
  return null;
}

function errorCode(error:unknown):string|undefined {
  return (error as NodeJS.ErrnoException).code;
}

async function listen(server:Server, path:string):Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const failed = (error:Error) => {
      server.off('listening', ready);
      reject(errorCode(error) === 'EADDRINUSE' ? new Error(busyMessage) : error);
    };
    const ready = () => {
      server.off('error', failed);
      resolve();
    };
    server.once('error', failed);
    server.once('listening', ready);
    server.listen(path);
  });
}

async function clearLegacyLock(path:string):Promise<void> {
  let source:string;
  try {
    source = await readFile(path, 'utf8');
  } catch (error) {
    if (errorCode(error) === 'ENOENT') return;
    throw error;
  }
  let record:{version?:number;pid?:number}|undefined;
  try {
    record = JSON.parse(source);
  } catch {
    // An older app could have just created its file, before writing the PID.
    await new Promise(resolve => setTimeout(resolve, 1000));
    try {
      record = JSON.parse(await readFile(path, 'utf8'));
    } catch (error) {
      if (!(error instanceof SyntaxError) && errorCode(error) !== 'ENOENT') throw error;
    }
  }
  const pid = record?.pid;
  if (record?.version !== 2 && typeof pid === 'number' && Number.isInteger(pid) && pid > 0 && pid <= 0x7fffffff) {
    const created = await processCreatedAt(pid);
    const lock = await stat(path).catch(error => {
      if (errorCode(error) === 'ENOENT') return null;
      throw error;
    });
    // Reusing a PID cannot keep an abandoned legacy lock alive indefinitely.
    if (created !== null && lock && created > lock.mtimeMs) {
      await rm(path, {force:true});
      return;
    }
    try {
      process.kill(pid, 0);
      throw new Error(busyMessage);
    } catch (error) {
      if (errorCode(error) !== 'ESRCH') {
        if (errorCode(error) === 'EPERM') throw new Error(busyMessage);
        throw error;
      }
    }
  }
  // Version 2 is protected by the OS endpoint, whose ownership we now hold.
  await rm(path, {force:true});
}

/** An OS-owned endpoint disappears on exit, even after a crash or SIGKILL. */
export async function withInstallationLock<T>(configFile:string, operation:()=>Promise<T>):Promise<T> {
  await mkdir(dirname(configFile), {recursive:true, mode:0o700});
  const canonical = join(await realpath(dirname(configFile)), basename(resolve(configFile)));
  const identity = process.platform === 'win32' ? canonical.toLowerCase() : canonical;
  const key = createHash('sha256').update(identity).digest('hex');
  const endpoint = process.platform === 'win32'
    ? '\\\\.\\pipe\\astrabridge-management-' + key
    : '\0astrabridge-management-' + key;
  // Connections do not participate in the mutex and must not delay close().
  const server = createServer(socket => socket.destroy());
  await listen(server, endpoint);
  const path = configFile + '.lock';
  let ownsFile = false;
  try {
    await clearLegacyLock(path);
    await writeFile(path, JSON.stringify({version:2, pid:process.pid}), {flag:'wx', mode:0o600});
    ownsFile = true;
    return await operation();
  } finally {
    // Close the OS mutex even if removal fails (for example, a full/unmounted FS).
    try {
      if (ownsFile) await rm(path, {force:true});
    } finally {
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
  }
}
