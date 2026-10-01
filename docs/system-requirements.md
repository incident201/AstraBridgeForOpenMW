# System requirements

AstraBridge packages the engine, Python, FFmpeg and the private game display in
its OCI image. Host prerequisites provide containers, GPU access and the Desktop
window. A host FFmpeg, Python or OpenMW installation is not required to run a
packaged release. Game files must be supplied by the user.

## Linux x86_64

| Component | Requirement |
| --- | --- |
| OS | A maintained x86_64 Linux distribution with glibc; Ubuntu 24.04 is the container/build baseline. Other distributions must provide the host facilities below. |
| Containers | Podman 5 or newer, **crun**, configured rootless user namespaces, subordinate UID/GID ranges and `newuidmap`/`newgidmap`. Podman's rootless networking helper (`pasta` or supported `slirp4netns`) must work. |
| Storage | A local filesystem supported by rootless Podman, such as ext4 or XFS, with writable storage and enough free space/inodes. Do not place Podman's graph directory directly on SMB/NFS. Game and recording folders may be elsewhere if their permissions and mount behavior allow it. |
| Graphics | A working host GPU driver and hardware OpenGL 3.3 or newer through the container's private Weston/XWayland session. Intel/AMD need accessible DRM render nodes; NVIDIA additionally needs the Container Toolkit/CDI integration below. |
| Desktop GUI | A host X11 or Wayland session and the shared libraries required by Electron: GTK 3, NSS/NSPR, D-Bus, ATK/AT-SPI, CUPS, X11/XCB, XKB, DRM/GBM and ALSA. The CLI does not create a window, but uses the same packaged executable. |
| AppImage | Kernel FUSE access for mounted execution. The pinned static AppImage runtime bundles its userspace FUSE library. On systems without FUSE, use `APPIMAGE_EXTRACT_AND_RUN=1` and a writable temporary directory. |
| Network | HTTPS access to GitHub Releases and GHCR for installation/explicit updates. Normal gameplay uses loopback HTTP/WebSocket and WebRTC TCP, ports 18770 and 18771. Only one default installation may be running on these ports at a time. |

For Ubuntu 24.04, typical host packages are:

```sh
sudo apt install podman crun uidmap passt fuse-overlayfs \
  libgtk-3-0t64 libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 \
  libatk-bridge2.0-0t64 libatspi2.0-0t64 libcups2t64 libx11-6 libxcb1 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libxkbcommon0 \
  libdrm2 libgbm1 libasound2t64
```

Package names differ by distribution. `podman info` must work as the same user
who launches AstraBridge. Membership in a render/video group or an equivalent
ACL must allow that user to access the selected render devices. Sign out and
back in after changing group membership. The backend explicitly uses crun with
`--group-add keep-groups` to preserve this access inside the rootless container.
See [Podman's device/group documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html).

SELinux installations need a policy permitting the selected game/recording bind
mounts and GPU devices. AstraBridge does not relabel the original game tree or
disable host security automatically. Configure appropriate container file labels
and device policy using the distribution's Podman guidance. Diagnose denied
access before changing policy; a successful host `glxinfo` alone does not prove
container access.

### NVIDIA and hybrid graphics

Install a supported host NVIDIA driver and **NVIDIA Container Toolkit with CDI**.
The pinned NVENC headers target Video Codec SDK 13.0.19 and require NVIDIA driver
570.0 or newer for NVENC. This encoder requirement is independent of OpenGL
rendering support.
The CDI specification must expose `nvidia.com/gpu=all` to Podman and supply the
matching graphics, CUDA/NVENC and utility libraries. Verify the specification
with `nvidia-ctk cdi list`; after a driver/device change, refresh it according to
the toolkit's instructions. Do not combine a legacy NVIDIA OCI hook with CDI
injection. See [NVIDIA's Podman/CDI guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html).

AstraBridge passes render nodes and NVIDIA CDI devices into its private display;
it does not mount the host X server. Selecting the NVIDIA device applies the
OpenGL PRIME offload environment inside the runtime. `prime-run astrabridge start`
is also recognized as a request for NVIDIA rendering. Selecting a GPU explicitly
in Settings or with `start --gpu GPU_ID` avoids depending on a host wrapper.
Actual OpenGL and encoder probes must succeed. Host PRIME support alone is not a
substitute for the private Weston/XWayland test. See [GPU selection](gpu-selection.md).

Hardware H.264 support is optional. `auto` falls back to CPU if encoding probes
fail. This guarantees an available codec, **not** enough CPU performance for
1080p60 at all workloads.

## Capacity planning

Start with 4 CPU cores, 8 GiB RAM and 15 GiB free for the application, image and
managed state, plus game files, optional game copies and recordings. These are
planning recommendations, not measured minimums or a 60 fps guarantee. Leave
room for old/new images and a state snapshot during updates. Recording sizes
vary with scene content and encoding mode; there is no fixed bitrate quota.

Native builds benefit from 16 GiB RAM and a 60–100 GiB workspace with ample
inodes. Lower the parallel job count on smaller machines. A loop-mounted ext4
workspace is an optional remedy for filesystem limitations, not a deployment
requirement. Every build/test path is selected by the developer; no particular
username, disk, mount point or GPU number is required.

## Windows x86_64

Use Windows 11 with virtualization/WSL components enabled, **WSL 2.9.3 or newer
including `wslc.exe`**, and a current GPU driver supporting WSL GPU access.
Install/update WSL following the [Microsoft WSL Containers guide](https://learn.microsoft.com/en-us/windows/wsl/wsl-container).
Verify `wsl --version` and `wslc version`. If the required release is still in
preview on your update channel, follow Microsoft's preview installation guidance.

No Docker Desktop, nested Podman or separate user Linux distribution is needed.
The backend uses WSL Containers directly. The EXE contains Electron/Node; the
Linux image supplies the game runtime and Mesa. Hardware graphics still needs a
successful Mesa D3D12 → Weston headless → XWayland → GLX probe. Encoding needs an
independent VAAPI/D3D12 or NVENC real-frame probe; CPU fallback remains available.

## Building and testing from source

On the Linux build host install Git, Python 3.12+, Podman and crun. Native C++,
CMake, Ninja, Lua and FFmpeg build dependencies are installed in the builder
image by `runtime/container/Containerfile`; they do not need host installations.
Download access is needed for the pinned base image, apt packages, source
archives, pip and npm dependencies. The build honors proxy configuration;
`--no-proxy` disables forwarding proxy variables into build containers explicitly.

Desktop development requires Node 24+ and npm; use `npm ci` with the committed
lockfile. Python tests use `runtime/requirements-dev.txt`. Install Lua 5.4 and a
C++ compiler for source tests that exercise Lua fixtures and the small native
media-clock program. Windows EXE packaging also needs MSVC Build Tools (the
console launcher is compiled with `cl.exe`) and a Windows build environment.

See [Development](development.md) for commands, cache locations and test setup.
Real game tests require the user's game installation and an explicitly selected
save. CPU recording tests need neither game data nor GPU hardware.
