import {readdir,stat} from 'node:fs/promises';
import {isAbsolute,resolve,relative,sep} from 'node:path';

export function isContainedRelativePath(path:string,separator=sep,absolute=isAbsolute):boolean {
  return !absolute(path) && path !== '..' && !path.startsWith('..' + separator);
}

/** Recognize conventional folder layouts, without guessing language/load order. */
export async function gameDataDirectory(game:string,override?:string){
  const root=resolve(game);
  if(override){
    const path=resolve(root,override),rel=relative(root,path);
    if(!isContainedRelativePath(rel)||!(await stat(path)).isDirectory())throw new Error('Data directory must be inside the game folder');
    return rel||'.';
  }
  const entries=await readdir(root,{withFileTypes:true});
  const data=entries.filter(e=>e.isDirectory()&&e.name.toLowerCase()==='data files');
  if(data.length===1)return data[0].name;
  if(entries.some(e=>e.isFile()&&e.name.toLowerCase()==='morrowind.esm'))return '.';
  throw new Error('Select the Morrowind folder containing Data Files, or Data Files itself. For a custom layout, set its subfolder in Advanced.');
}
