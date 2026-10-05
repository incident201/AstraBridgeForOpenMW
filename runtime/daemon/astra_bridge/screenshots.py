"""Only resized observations reach disk; recording retains the native buffer."""
def observation_size(width, height):
    scale = min(1, 1280/width, 720/height)
    return max(1,round(width*scale)),max(1,round(height*scale))


def save_bgra(path, pixels, width, height, *, bottom_up=False, native_size=False):
    from PIL import Image
    image = Image.frombytes('RGB', (width,height), bytes(pixels), 'raw', 'BGRX', 0, -1 if bottom_up else 1)
    size = (width,height) if native_size else observation_size(width,height)
    if image.size != size: image = image.resize(size, Image.Resampling.LANCZOS)
    image.save(path, format='PNG')
    return {'width':size[0], 'height':size[1], 'render_width':width, 'render_height':height}
