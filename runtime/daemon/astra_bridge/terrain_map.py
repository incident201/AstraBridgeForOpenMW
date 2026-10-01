"""SVG of public relative survey samples; never reads engine positions or maps."""
from html import escape
from pathlib import Path
import math


def render_terrain(observation: dict, path: Path) -> None:
    terrain=observation['terrain']
    cx,cy,scale=220,230,29
    lines=['<svg xmlns="http://www.w3.org/2000/svg" width="850" height="480" viewBox="0 0 850 480">',
           '<rect width="850" height="480" fill="#101923"/>',
           '<g font-family="sans-serif" fill="#d6e3ed" font-size="13">',
           '<text x="20" y="24">Local walking surface · front is up · sampled rays only</text>']
    for r in (2,4,6):
        lines.append(f'<circle cx="{cx}" cy="{cy}" r="{r*scale}" fill="none" stroke="#304151"/>')
        lines.append(f'<text x="{cx+4}" y="{cy-r*scale+14}" fill="#8b9caa">{r} m</text>')
    for ray in terrain.get('rays',[]):
        a=math.radians(ray['bearing_deg']);d=ray['clear_m']*scale
        x,y=cx+math.sin(a)*d,cy-math.cos(a)*d
        dz=ray['height_change_m']
        color='#7ebaff' if dz>.45 else '#ffa66d' if dz<-.45 else '#7ac9a3'
        lines.append(f'<path d="M {cx},{cy} L {x:.1f},{y:.1f}" stroke="{color}" opacity=".6" fill="none"/>')
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
    for i,p in enumerate(terrain.get('passages',[]),1):
        a=math.radians(p['bearing_deg']);d=p['distance_m']*scale
        x,y=cx+math.sin(a)*d,cy-math.cos(a)*d
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" fill="#d6e3ed"/>')
        lines.append(f'<text x="{x:.1f}" y="{y+4:.1f}" text-anchor="middle" fill="#101923">{i}</text>')
        label=f"{i}. {p['direction']}  {p['distance_m']} m / height {p['height_change_m']:+.2f} m"
        lines.append(f'<text x="445" y="{78+i*38}">{escape(label)}</text>')
        lines.append(f'<text x="465" y="{94+i*38}" fill="#91a4b3" font-size="11">{escape(p["status"])}</text>')
    lines.extend(['<path d="M 220,215 L 211,239 L 220,234 L 229,239 Z" fill="#ffffff"/>',
                  '<text x="20" y="450">Blue: up · orange: down · green: level. Gaps between rays are unknown.</text>',
                  f'<text x="445" y="65">{escape(observation.get("location",""))}</text>', '</g></svg>'])
    path.write_text('\n'.join(lines),encoding='utf-8')
