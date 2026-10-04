const fs=require('node:fs/promises');
const path=require('node:path');
module.exports=async context=>{
  if(context.electronPlatformName==='linux'){
    const directory=context.appOutDir;
    await fs.rename(path.join(directory,'astrabridge-desktop'),path.join(directory,'astrabridge-bin'));
    const script=`#!/bin/sh
set -eu
astra_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Electron cannot run JavaScript diagnostics when a host shared library is
# missing. Report the loader's actual missing SONAMEs before starting it.
if command -v ldd >/dev/null 2>&1; then
  astra_missing=$(LC_ALL=C ldd "$astra_dir/astrabridge-bin" 2>&1 | awk '/=> not found/ {print $1} /version .* not found/ {print}')
  if [ -n "$astra_missing" ]; then
    astra_message="AstraBridge cannot start. Missing or incompatible system libraries:
$astra_missing

Install the packages providing these libraries for your distribution.
See the Linux Desktop dependencies in docs/system-requirements.md."
    printf '%s\\n' "$astra_message" >&2
    if [ -n "\${DISPLAY:-}\${WAYLAND_DISPLAY:-}" ]; then
      if command -v kdialog >/dev/null 2>&1; then kdialog --error "$astra_message" --title AstraBridge || true
      elif command -v zenity >/dev/null 2>&1; then zenity --error --title=AstraBridge --text="$astra_message" || true
      fi
    fi
    exit 1
  fi
fi
# AppRun may prepend this Electron flag when user namespaces are unavailable.
# Keep it for GUI startup; it is not an AstraBridge CLI command.
astra_no_sandbox=0
if [ "\${1-}" = --no-sandbox ]; then
  astra_no_sandbox=1
  shift
fi
if [ "$#" -gt 0 ]; then
  export ELECTRON_RUN_AS_NODE=1
  export ASTRA_RESOURCES="$astra_dir/resources/astra"
  export ASTRA_EXECUTABLE="\${APPIMAGE:-$astra_dir/astrabridge}"
  exec "$astra_dir/astrabridge-bin" "$astra_dir/resources/app.asar/out/cli.cjs" "$@"
fi
unset ELECTRON_RUN_AS_NODE
if [ "$astra_no_sandbox" = 1 ]; then
  exec "$astra_dir/astrabridge-bin" --no-sandbox
fi
exec "$astra_dir/astrabridge-bin" "$@"
`;
    await fs.writeFile(path.join(directory,'astrabridge-desktop'),script,{mode:0o755});
    await fs.writeFile(path.join(directory,'astrabridge'),script,{mode:0o755});
  }else if(context.electronPlatformName==='win32'){
    await fs.access(path.join(context.appOutDir,'resources/astra/cli-launcher.exe'));
    const shim=path.join(__dirname,'astrabridge.exe');
    await fs.access(shim);
    await fs.copyFile(shim,path.join(context.appOutDir,'astrabridge.exe'));
  }
};
