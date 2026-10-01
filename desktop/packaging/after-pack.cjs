const fs=require('node:fs/promises');
const path=require('node:path');
module.exports=async context=>{
  if(context.electronPlatformName==='linux'){
    const directory=context.appOutDir;
    await fs.rename(path.join(directory,'astrabridge-desktop'),path.join(directory,'astrabridge-bin'));
    const script=`#!/bin/sh
set -eu
astra_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -gt 0 ]; then
  export ELECTRON_RUN_AS_NODE=1
  export ASTRA_RESOURCES="$astra_dir/resources/astra"
  export ASTRA_EXECUTABLE="\${APPIMAGE:-$astra_dir/astrabridge}"
  exec "$astra_dir/astrabridge-bin" "$astra_dir/resources/app.asar/out/cli.cjs" "$@"
fi
unset ELECTRON_RUN_AS_NODE
exec "$astra_dir/astrabridge-bin" "$@"
`;
    await fs.writeFile(path.join(directory,'astrabridge-desktop'),script,{mode:0o755});
    await fs.writeFile(path.join(directory,'astrabridge'),script,{mode:0o755});
  }else if(context.electronPlatformName==='win32'){
    const shim=path.join(__dirname,'astrabridge.exe');
    await fs.access(shim);
    await fs.copyFile(shim,path.join(context.appOutDir,'astrabridge.exe'));
  }
};
