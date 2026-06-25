# petkit/eyes.py
"""Cursor-tracking pixel eyes for the sprite cat.

`pupil_offset` is the pure deflection math: how far the white catchlight dot
drifts within an eye toward the cursor.

`EYES[state]` is a per-frame table describing where the cat's eyes are in each
animation frame. Each entry is one of:
  * ``None``            -- the eyes are CLOSED this frame; draw nothing.
  * ``((lx,ly),(rx,ry))`` -- the two eyes are OPEN; the pairs are the TOP-LEFT
    corners (in 32-space sprite coordinates) of each eye's 2x2 pixel block.

An open eye in the sprite is a 2x2 block of 3 black pupil cells + 1 white
catchlight; the renderer paints a black 2x2 base over that block and floats a
1px white dot inside it toward the cursor. Because the cat bobs down 1px
mid-cycle, the open-eye rows shift between frames, so the eyes are re-seated
each frame from this table. ``None`` frames are how closed-eye poses (e.g. a
future box/sleep sheet) are expressed -- the renderer draws no eyes at all.
"""
import math


def pupil_offset(dx, dy, reach=55.0, max_off=1.4):
    """Offset (ox,oy) in sprite px for a pupil whose eye is `dx,dy` screen px
    from the cursor: points toward the cursor, grows with distance up to
    `reach`, clamped to `max_off` sprite px."""
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return (0.0, 0.0)
    f = min(1.0, d / reach) * max_off / d
    return (dx * f, dy * f)


EYES = {
    # Faithful to assets/cat/Idle.png (10 frames). Each open eye is a 2x2 block
    # whose TOP-LEFT corner is given below: LEFT eye x=6, RIGHT eye x=13.
    # The cat bobs down 1px for frames 3-6, so y goes 12 -> 13 there.
    "idle": [
        ((6, 12), (13, 12)),   # 0
        ((6, 12), (13, 12)),   # 1
        ((6, 12), (13, 12)),   # 2
        ((6, 13), (13, 13)),   # 3
        ((6, 13), (13, 13)),   # 4
        ((6, 13), (13, 13)),   # 5
        ((6, 13), (13, 13)),   # 6
        ((6, 12), (13, 12)),   # 7
        ((6, 12), (13, 12)),   # 8
        ((6, 12), (13, 12)),   # 9
    ],
}
