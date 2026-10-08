export interface Field {name:string;options:string[];type:'boolean'|'number'|'json'|'string';integer?:boolean;required:boolean;optional:boolean;array:boolean;default?:unknown;choices?:unknown[];help?:string}
export interface Command {operation:string;description:string;fields:Field[];exclusive:string[][]}
export type Catalog=Record<string,Command>;

export function parseGame(catalog:Catalog, argv:string[]){
  const [name,...tokens]=argv;const command=catalog[name];
  if(!command)throw new Error(`Unknown game command: ${name??''}. Use astrabridge game --help.`);
  const args:Record<string,any>={};const used=new Set<string>();
  for(const field of command.fields)if('default' in field)args[field.name]=structuredClone(field.default);
  const positional=command.fields.filter(field=>field.options.length===0);let position=0;
  const convert=(field:Field,raw:string):unknown=>{
    let value:unknown=raw;
    if(field.type==='number'){value=Number(raw);if(!Number.isFinite(value)||field.integer&&!Number.isInteger(value))throw new Error(`Expected ${field.integer?'an integer':'a number'} for ${field.name}`);}
    if(field.type==='json')value=JSON.parse(raw);
    if(field.choices&&!field.choices.includes(value))throw new Error(`Invalid ${field.name}: choose ${field.choices.join(', ')}`);
    return value;
  };
  let positionalOnly=false;
  for(let i=0;i<tokens.length;i++){
    const token=tokens[i];
    if(token==='--'&&!positionalOnly){positionalOnly=true;continue;}
    if(token.startsWith('--')&&!positionalOnly){
      const equals=token.indexOf('=');const flag=equals<0?token:token.slice(0,equals);
      const field=command.fields.find(field=>field.options.includes(flag));
      if(!field)throw new Error(`Unknown option ${flag}`);
      used.add(field.name);
      if(field.type==='boolean'){
        if(equals>=0)throw new Error(`${flag} does not take a value`);
        args[field.name]=!(field.options.length>1&&flag.startsWith('--no-'));
      }else{
        const raw=equals<0?tokens[++i]:token.slice(equals+1);
        if(raw===undefined)throw new Error(`Missing value for ${flag}`);
        const value=convert(field,raw);
        if(field.array)(args[field.name]??=[]).push(value);else args[field.name]=value;
      }
    }else{
      const field=positional[position++];if(!field)throw new Error(`Unexpected argument ${token}`);
      used.add(field.name);args[field.name]=convert(field,token);
    }
  }
  for(const field of command.fields)if(field.required&&!field.optional&&!used.has(field.name))throw new Error(`Missing ${field.options[0]??field.name}`);
  for(const group of command.exclusive)if(group.filter(name=>used.has(name)).length>1)throw new Error(`Choose only one of ${group.join(', ')}`);
  const pretty=Boolean(args.pretty);delete args.pretty;
  let result=args;
  if(['act','chain','sequence'].includes(name)){
    result=JSON.parse(args.json);
    if(!result||Array.isArray(result)||typeof result!=='object')throw new Error('Expected a JSON object');
    for(const key of ['full','request_id'])if(key in args)result[key]=args[key];
  }
  if(name==='read'&&!result.all)delete result.all;
  return {op:command.operation,args:result,pretty};
}

export function gameHelp(catalog:Catalog,name?:string){
  if(!name)return 'Usage: astrabridge game <command> [arguments]\n\n'+Object.keys(catalog).sort().join('  ');
  const command=catalog[name];if(!command)throw new Error('Unknown game command');
  return `Usage: astrabridge game ${name} [arguments]\n${command.description}\n\n`+
    command.fields.map(field=>`${field.options.join(', ')||field.name}${field.type==='boolean'?'':` <${field.type}>`}${field.required&&!field.optional?' (required)':''}${field.help?' — '+field.help:''}`).join('\n');
}
