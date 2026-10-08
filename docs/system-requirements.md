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

The optional [AstraBridge Runner](agent-runner.md) additionally requires
host Python 3.11+ and its installed Python dependencies, plus HTTPS access to
OpenAI's authentication/API endpoints or the selected DeepSeek endpoint.
Python is not required merely to use the packaged
Desktop or its normal CLI.

### Container packages

Install the host packages appropriate for your distribution; the application
checks the actual tools and configuration, not whether one particular package
manager reports a package name.

| Capability | Debian / Ubuntu packages | Arch / CachyOS packages |
| --- | --- | --- |
| Container manager | `podman` **5+** | `podman` **5+** |
| OCI runtime | `crun` | `crun` |
| Default rootless networking (`pasta`) | `passt` | `passt` |
| UID/GID mapping helpers | `uidmap` | `shadow` |
| Download terminal and storage tools | `util-linux`, `coreutils` | `util-linux`, `coreutils` |
| NVIDIA container integration, when exposing NVIDIA | `nvidia-container-toolkit` from NVIDIA's supported repository | `nvidia-container-toolkit` |

Podman's package dependencies provide its monitor/network/configuration tools,
such as conmon, Netavark and containers-common. Install the complete package with
its dependencies. `slirp4netns` is an alternative only when Podman is configured
to use it; installing it does not satisfy a configuration that selects `pasta`.
`fuse-overlayfs` is an optional storage fallback, not a universal requirement.

For Arch/CachyOS:

```sh
sudo pacman -S --needed podman crun passt shadow
# Add this when the runtime will expose an NVIDIA GPU:
sudo pacman -S --needed nvidia-container-toolkit
```

For Debian/Ubuntu, use a supported repository providing **Podman 5 or newer**:

```sh
sudo apt install podman crun uidmap passt
podman --version
```

Ubuntu 24.04's standard [Podman package](https://packages.ubuntu.com/en/noble/podman)
is 4.9.x and does **not** meet this requirement. The image's Ubuntu 24.04 base is
not a statement that the host's default Podman version is sufficient. Choose a
supported host release/repository with Podman 5+; installing an older package
will be reported as an unmet requirement. For NVIDIA on Debian/Ubuntu, follow
[NVIDIA's package installation instructions](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
for `nvidia-container-toolkit` and its dependencies.

### Desktop libraries and AppImage

The AppImage includes Electron/Node and application code. The Linux system must
provide glibc and the ordinary Desktop libraries: GLib/GObject/GIO, GTK 3,
Pango/Cairo, NSS/NSPR, D-Bus, ATK/AT-SPI, CUPS, X11/XCB, XKB, DRM/GBM, udev,
Expat, ALSA and their normal package dependencies. These are needed even for CLI
mode because it uses the same Electron executable. GUI mode additionally needs
a working host X11 or Wayland session.

Typical Ubuntu 24.04 library packages (independent of the Podman version caveat):

```sh
sudo apt install libgtk-3-0t64 libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 \
  libatk-bridge2.0-0t64 libatspi2.0-0t64 libcups2t64 libx11-6 libxcb1 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libxkbcommon0 \
  libdrm2 libgbm1 libasound2t64 libudev1 libexpat1
```

Typical Arch/CachyOS library packages:

```sh
sudo pacman -S --needed gtk3 nss nspr dbus at-spi2-core libcups libx11 libxcb \
  libxcomposite libxdamage libxext libxfixes libxrandr libxkbcommon libdrm \
  mesa alsa-lib systemd-libs expat
```

The launcher uses the system `ldd` utility to identify unresolved libraries and
ABI version requirements before starting Electron. It prints the actual missing
library names and, when available, uses KDialog or Zenity to display the message
for a launch from the desktop. Those dialog utilities are optional. A failed
ELF loader cannot reach the application's Setup screen.

Mounted AppImage execution needs `/dev/fuse`; the pinned runtime includes its
userspace FUSE library. If FUSE is unavailable, launch with
`APPIMAGE_EXTRACT_AND_RUN=1` and a writable temporary directory. This occurs
before the application launcher and its diagnostics can run.

### Rootless configuration and permissions

Package names differ by distribution. `podman info` must work as the same user
who launches AstraBridge. Membership in a render/video group or an equivalent
ACL must allow that user to access the selected render devices. Sign out and
back in after changing group membership. Mapping tools must retain their distribution-provided setuid bits or file
capabilities; executable files alone are not sufficient. The backend explicitly uses crun with
`--group-add keep-groups` to preserve this access inside the rootless container.
See [Podman's device/group documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html).

SELinux installations need a policy permitting the selected game/recording bind
mounts and GPU devices. AstraBridge does not relabel the original game tree or
disable host security automatically. Configure appropriate container file labels
and device policy using the distribution's Podman guidance. Diagnose denied
access before changing policy; a successful host `glxinfo` alone does not prove
container access.

### GPU requirements by vendor

| Rendering GPU | Required on the Linux host | Provided inside the AstraBridge image |
| --- | --- | --- |
| Intel | A compatible kernel driver (`i915` or `xe`), firmware and an accessible DRM render node. | Mesa OpenGL and Intel VAAPI userspace driver. |
| AMD | A compatible kernel driver (normally `amdgpu`), firmware and an accessible DRM render node. | Mesa OpenGL and Mesa VAAPI drivers. |
| NVIDIA | A working proprietary/open-kernel NVIDIA driver with matching userspace libraries, NVIDIA Container Toolkit and CDI device registration. | The graphics/encoding clients; vendor libraries are injected from the host through CDI. |
| Hybrid Intel/AMD + NVIDIA | Requirements for both devices exposed to the runtime. User permissions must cover every passed render device. | Private compositor on Mesa where available, with NVIDIA offload for the selected game GPU. |

The runtime normally exposes all detected render devices and NVIDIA CDI devices.
Selecting Intel/AMD rendering on a hybrid laptop does not remove the need for
CDI when NVIDIA is also exposed for rendering or encoding. Intel/AMD-only hosts
do not need NVIDIA packages. `prime-run` is an optional convenience; GPU selection
is also available in AstraBridge Settings.

Install drivers/firmware using your distribution's hardware support packages.
Host desktop Mesa/GL libraries serve the host application; the game's Mesa and
VAAPI userspace libraries come from the image. Installing host VAAPI packages
cannot repair a missing kernel render device or change the container's pinned
encoder build. CUDA Toolkit, a host FFmpeg, Weston, XWayland, Python and OpenMW
are not separate production host dependencies.

All hardware-rendering paths must pass the runtime's real OpenGL probe (3.3+,
correct requested vendor, no software renderer). The existence of a device node
alone does not prove that the GPU supports the required GL context. Hardware
encoding is optional and probed independently; GPU models and drivers differ
in H.264 encoding support. Explicit software rendering is a diagnostic mode,
not a promise of real-time 1080p60 performance.

### NVIDIA and hybrid graphics

Install a supported host NVIDIA driver and **NVIDIA Container Toolkit with CDI**.
The pinned NVENC headers target Video Codec SDK 13.0.19 and require NVIDIA driver
570.0 or newer for NVENC. This encoder requirement is independent of OpenGL
rendering support.
The CDI specification must expose `nvidia.com/gpu=all` to Podman and supply the
matching graphics, CUDA/NVENC and utility libraries. Verify the specification
with `nvidia-ctk cdi list`; it must include `nvidia.com/gpu=all`. After a
driver/device change, refresh CDI using your distribution's toolkit integration.
Arch/CachyOS packages provide a pacman hook; other distributions may provide
`nvidia-cdi-refresh` systemd units. A manual refresh is:

```sh
sudo mkdir -p /etc/cdi
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
nvidia-ctk cdi list
```

Do not combine a legacy NVIDIA OCI hook with CDI
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

## Automatic checks and their limits

Desktop checks host prerequisites when it opens and exposes the results in
**Setup → System requirements**. Missing components are collected into one
report with remediation guidance. **Check again** refreshes the report after
manual installation/configuration. Neither the check nor the application installs
host packages or changes host driver/security configuration automatically.

On Linux the checks cover Podman version, crun, UID/GID mapping tools and ranges,
namespace restrictions (including a diagnostic namespace probe where available),
available networking helper, render-node permissions and
kernel driver identity. NVIDIA devices additionally require a working
`nvidia-smi`, `nvidia-ctk`, and a registered `nvidia.com/gpu=all` CDI device. An old
NVENC driver is a recording warning because CPU encoding remains available.

Before install, start or update, the backend repeats these checks and validates
rootless Podman against the selected managed storage, including actual UID/GID
mappings, the configured monitor/network backend and selected rootless network
helper. Failures stop the operation before
image downloads or container replacement. CLI operations return the same
requirements report. Help and version remain usable without Podman.

Host checks do not create a test container and do not certify every driver/image
combination. The runtime's OpenGL and actual-frame encoding probes remain the
final checks of hardware rendering/recording. Filesystem capacity, network access,
display-session availability and host security policy must also meet the
requirements above; a package-presence check cannot guarantee those conditions.

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
The backend uses WSL Containers directly. The portable ZIP includes Electron/Node,
the GUI, the CLI launcher and application dependencies; keep the extracted files
together. There is no desktop installer. The
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
media-clock program. Windows package builds use MSVC Build Tools (the
console launcher is compiled with `cl.exe`) and a Windows build environment.

See [Development](development.md) for commands, cache locations and test setup.
Real game tests require the user's game installation and an explicitly selected
save. CPU recording tests need neither game data nor GPU hardware.

### Managed-storage removal on Linux

Keep `script`, `unshare` and `umount` (util-linux) and `rm`/`stty` (coreutils) installed alongside
Podman. The prerequisite checker verifies these commands. They let Desktop clean
UID-mapped files in its selected managed store without sudo; original game files,
recordings and other stores are retained. The standard packages on supported
Linux desktop distributions normally already provide these tools.

`script` and `stty` provide a private terminal for Podman's image download counters. It is
checked before installation and startup. No host graphical terminal or display
session is needed for this progress reporting.
