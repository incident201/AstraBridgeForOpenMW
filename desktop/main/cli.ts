import {readFile} from 'node:fs/promises';
import {dirname,join} from 'node:path';
import {Core} from './core';
import {gameHelp,parseGame,type Catalog} from './game-cli';

const argv=process.argv.slice(2);
function take(name:string){const index=argv.indexOf(name);if(index<0)return undefined;if(index===argv.length-1)throw new Error(`Missing ${name}`);return argv.splice(index,2)[1];}
const config=take('--config');
const resources=process.env.ASTRA_RESOURCES??join(dirname(process.execPath),'resources/astra');
const core=new Core(resources,config,text=>process.stderr.write(typeof text==='string'?text:text.type==='stage'?text.message+'\n':`${text.phase}: ${(text.received/1048576).toFixed(1)} MiB received, ${text.elapsed.toFixed(0)}s elapsed\n`));
const help=`AstraBridge Desktop and CLI

Usage: astrabridge [--config FILE] <command>
  install --game DIRECTORY --storage DIRECTORY --encoding win1250|win1251|win1252
          [--game-mode mount|copy] [--recordings DIRECTORY] [--data-relative "Data Files"]
          [--development --repository DIRECTORY]
  start [--gpu auto|nvidia|GPU_ID] | stop [--without-save | --cancel] | restart [--gpu auto|nvidia|GPU_ID] | status | update
  agent connect [--name NAME] [--profile ID] | disconnect | status
  game <command> [arguments]
  config show | set JSON
  gpus
  recordings
  logs [--name FILE]
  cli install | status | uninstall
  skill export DIRECTORY
  version

Run astrabridge without arguments to open Desktop.
Use astrabridge game --help for gameplay commands.
`;

async function main(){
  const command=argv.shift();
  if(!command||command==='--help'||command==='-h'){console.log(help);return;}
  let result:any;let pretty=Boolean(argv.includes('--pretty'));
  if(command==='game'){
    const catalog:Catalog=JSON.parse(await readFile(join(resources,'game-commands.json'),'utf8'));
    if(argv.includes('--help')||argv.includes('-h')||!argv.length){console.log(gameHelp(catalog,argv[0]?.startsWith('-')?undefined:argv[0]));return;}
    const request=parseGame(catalog,argv);pretty=request.pretty;result=await core.game(request.op,request.args);
  }else if(command==='install'){
    const game=take('--game'),storage=take('--storage'),encoding=take('--encoding');
    if(!game||!storage||!encoding)throw new Error('install requires --game, --storage and --encoding');
    const dataRelative=take('--data-relative'),recordings=take('--recordings'),gameMode=take('--game-mode') as 'mount'|'copy'|undefined;
    const development=argv.includes('--development'),repository=take('--repository');
    result=await core.install({game,storage,encoding,recordings,gameMode,dataRelative,development,repository});
  }else if(['start','stop','restart','status','update'].includes(command)){
    const gpu=take('--gpu');
    if(gpu&&!['auto','nvidia'].includes(gpu)&&!/^pci:[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$/.test(gpu))throw new Error('Use a GPU ID from astrabridge gpus, auto or nvidia');
    if(command==='start'||command==='restart')result=await core[command](gpu);
    else if(command==='stop'){
      if(argv.includes('--without-save')&&argv.includes('--cancel'))throw Error('Choose --without-save or --cancel');
      if(argv.includes('--cancel'))result=await core.cancelSessionStop();
      else result=await (argv.includes('--without-save')?core.stop():core.stopSession());
    }else result=await core[command as 'status'|'update']();
  }else if(command==='cli'){
    const action=argv.shift();
    if(action==='install')result=await core.installCli();
    else if(action==='uninstall')result=await core.uninstallCli();
    else if(action==='status')result=await core.cliStatus();
    else throw Error('Use cli install, cli status or cli uninstall');
  }else if(command==='agent'){
    const action=argv.shift();
    if(action==='connect')result=await core.connect(take('--name'),take('--profile'));
    else if(action==='disconnect')result=await core.disconnect();
    else if(action==='status')result=await core.agentStatus();
    else throw new Error('Use agent connect, disconnect or status');
  }else if(command==='config'){
    const action=argv.shift();await core.ensureDaemon();
    if(action==='show')result=await core.api('/v1/runtime/config');
    else if(action==='set')result=await core.api('/v1/runtime/config','PATCH',JSON.parse(argv.join(' ')));
    else throw new Error('Use config show or config set JSON');
  }else if(command==='gpus'){await core.ensureDaemon();result=await core.api('/v1/runtime/gpus');}
  else if(command==='recordings'){
    const directory=await core.recordingsFolder(),items=await core.recordings.list(directory);
    for(const row of items)for(const key of ['video','metadata','encoder','diagnostics','events'])if(row[key])row[key]=await core.recordings.path(row[key].split('/').pop());
    result={directory,items};
  }
  else if(command==='logs')result=await core.logs(take('--name'));
  else if(command==='skill'&&argv.shift()==='export'){
    if(!argv[0])throw new Error('Provide a skill destination directory');
    result=await core.exportSkill(argv[0]);
  }else if(command==='version'||command==='--version')result=await core.release();
  else throw new Error(`Unknown command ${command}. Use --help.`);
  console.log(JSON.stringify({ok:true,result},null,pretty?2:undefined));
}
main().catch(error=>{console.log(JSON.stringify({ok:false,error:error.message,...error.details}));process.exitCode=1;});
