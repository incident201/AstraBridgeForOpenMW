# Rendering and encoding GPU selection

Rendering and H.264 encoding are independent choices. For example, render with a
discrete NVIDIA GPU and encode with Intel VAAPI, or use the same GPU for both.
The runtime enumerates devices visible **inside its container**, including their
names, PCI identities, render nodes and CUDA identities where available.

## Selecting devices

Open **Settings → Game GPU** and **Encoding GPU** after installation. Both default
to `auto`. Settings take effect on the next game start; stop the game before
editing. Encoding selection applies to recording and the live viewer. Recording
and live view still consume independent original frame/audio streams.

CLI equivalents:

```sh
astrabridge gpus
astrabridge config show
astrabridge config set '{"graphics_gpu":"pci:0000:02:00.0","encoding_gpu":"pci:0000:00:02.0"}'
astrabridge start
```

The PCI addresses above are examples: use IDs returned by `astrabridge gpus` on
your installation. A one-start override is available through
`astrabridge start --gpu GPU_ID` (or `restart --gpu GPU_ID`). `auto` and `nvidia`
are also accepted for this override; `nvidia` is a vendor preference for PRIME,
not a claim to distinguish multiple NVIDIA cards. `prime-run astrabridge start`
is translated to this NVIDIA rendering request. Saved explicit settings are the
preferred way to avoid wrapper/environment ambiguity.

PCI IDs are stored instead of enumeration positions such as GPU 0. If the selected
device is removed, hidden from the container or moved to another PCI address,
select an available device again. The runtime reports `selected_gpu_unavailable`
instead of silently choosing a different card. Auto mode may select a different
GPU when the environment changes.

## How rendering is selected

- Intel/AMD Mesa devices use `DRI_PRIME=pci-…`, constructed from the selected
  PCI identity, and `__GLX_VENDOR_LIBRARY_NAME=mesa`. Selecting the GLX vendor
  prevents a NVIDIA-backed XWayland server from overriding the Mesa request.
  See [Mesa's device-selection variables](https://docs.mesa3d.org/envvars.html#dri-prime).
- Linux NVIDIA uses `__NV_PRIME_RENDER_OFFLOAD=1` and
  `__GLX_VENDOR_LIBRARY_NAME=nvidia` in the private display's OpenGL client
  environment. Driver/library access comes from CDI, not the image. See
  [NVIDIA's hybrid-graphics guide](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/optimus-laptops-and-multi-gpu-desktop-systems.html).
- With several NVIDIA GPUs, exact rendering selection is currently unavailable
  until a reliable mapping to XWayland render providers is established. Those
  device entries are disabled for rendering selection. Generic NVIDIA preference
  and automatic mode do not promise which NVIDIA card renders.
- WSL uses Mesa D3D12. Exact selection depends on device identities exposed by
  WSL and the driver's adapter-name mapping.

`status`/Diagnostics shows the actual OpenGL renderer, acceleration result,
requested GPU and selected inventory entry. Hardware mode rejects software GL.
The renderer probe is an observation of the working GL context; an environment
variable alone is not evidence of acceleration. Changing the render choice
requires restarting OpenMW. The private compositor can use a different device
from the OpenMW client.

On hybrid Linux systems, the private Weston/XWayland session uses an accessible
Intel/AMD Mesa device when available. OpenMW can then use that device or NVIDIA
PRIME offload. This avoids importing Mesa client buffers into a NVIDIA compositor.
The runtime also locates the NVIDIA GBM module supplied by CDI: its directory can
differ between the host distribution and the container image. Vendor drivers
remain supplied by the host. No host compositor or desktop GPU settings are
changed. Shader caches are writable within the active profile's runtime storage.
The GL probe rejects a renderer from the wrong vendor for an explicit selection,
in addition to rejecting software rendering.

## How encoding is selected

The encoder setting remains `auto`, `cpu`, `vaapi` or `nvenc`.

- **Auto GPU** probes available NVENC/VAAPI paths, then CPU.
- **Explicit GPU** restricts probes to that physical device. VAAPI uses its
  render node; NVENC uses the CUDA ordinal resolved from that same PCI identity
  using the CUDA driver API. NVML/list ordering is not assumed to equal CUDA
  ordering. No other GPU is tried as a substitute.
- **Auto encoder** may fall back to libx264 after the chosen GPU's probe fails.
  **Explicit VAAPI/NVENC** reports failure if its probes fail. **CPU** bypasses
  GPU selection. Missing explicitly selected devices are reported immediately.
- `vaapi_device` is an advanced override for automatic GPU selection. It cannot
  be combined with `encoding_gpu`; the GUI clears it when selecting a GPU.

Every candidate must encode actual FrameStream BGRA data through its filters and
muxer. The viewer additionally probes its Baseline/Opus chain. Diagnostics and
`.encoder.json` retain attempts/failures; recording metadata includes the chosen
PCI ID for explicit selection, VAAPI node or CUDA index, FFmpeg identity and
quality mode. CPU fallback is visible in metadata and live status.
