import {build} from 'esbuild';
import {build as viteBuild} from 'vite';
import {mkdir,readFile,writeFile,cp,access} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

await mkdir('resources',{recursive:true});
const version=JSON.parse(await readFile('../VERSION.json','utf8'));
await cp('../skill','resources/skill',{recursive:true});
const python=process.env.ASTRA_BUILD_PYTHON??'python3';
const catalog=execFileSync(python,['-B','-m','astra_daemon.commands'],{env:{...process.env,PYTHONPATH:resolve('../runtime/daemon')},encoding:'utf8'});
await writeFile('resources/game-commands.json',catalog);
try{await access('resources/release.json');}catch{
  await writeFile('resources/release.json',JSON.stringify({version:version.project_version,
    image:'localhost/astrabridge-runtime:dev',digest:'',development:true,runtime_api:1,game_api:1},null,2)+'\n');
}
const common={bundle:true,platform:'node',format:'cjs',target:'node24',external:['electron'],sourcemap:true};
await build({...common,entryPoints:['main/main.ts'],outfile:'out/main.cjs'});
await build({...common,entryPoints:['main/cli.ts'],outfile:'out/cli.cjs'});
await build({...common,entryPoints:['preload/index.ts'],outfile:'out/preload.cjs'});
await viteBuild();
