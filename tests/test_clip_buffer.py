import numpy as np
from care_ladder.clip_buffer import ClipBuffer

def test_buffer_keeps_only_last_window():
    buf = ClipBuffer(seconds=2.0)
    for i in range(10):
        buf.push(np.full((4, 4, 3), i, dtype=np.uint8), t=float(i))
    snap = buf.snapshot(now=9.0)
    assert len(snap) >= 2
    # oldest kept frame should be at t>=7.0
    assert all(f[0, 0, 0] >= 7 for f in snap)
