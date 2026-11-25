"""Pixel trajectories plus the contact axes for one gesture.

The phone multiplies pixels by 8 and writes pressure, major, minor, and
orientation as given. Each call draws a new path and a new contact.
"""

import math
import random

from ninjatap.protocol import HEIGHT, WIDTH, Down, Move, Sleep, Step, Up

FRAME_MS = 17
TAP_MS = 60
TAP_MS_JITTER = 25
DRAG_BRAKE_MS = 400
DRAG_HOLD_MS = 500
DRAG_FRAME_JITTER = 8
DRAG_HOLD_JITTER = 6
HOLD_DRAG_MS = 500
HOLD_DRAG_MS_JITTER = 40
HOLD_DRAG_SETTLE_MS = 100
HOLD_DRAG_SETTLE_JITTER = 30
HOLD_DRAG_MIN_TRAVEL_MS = 280
HOLD_DRAG_MAX_TRAVEL_MS = 1600
FLICK_RISE_MS = 250
FLICK_MS_JITTER = 30
PINCH_MS = 612
TAP_JITTER = 4
HOLD_DRIFT_PX = 4


def tap(
    x: int, y: int, finger: int = 0, rng: random.Random | None = None,
    *, exact: bool = False, size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[Step]:
    """Hold one point for about 60ms, then lift. Exact taps keep the given coordinates."""
    rng = _rng(rng)
    if not exact:
        x += rng.randint(-TAP_JITTER, TAP_JITTER)
        y += rng.randint(-TAP_JITTER, TAP_JITTER)
    gaps = _frames(TAP_MS, TAP_MS_JITTER, rng, minimum=1)
    ages = [FRAME_MS * i for i in range(gaps + 1)]
    return _place([(x, y)] * len(ages), ages, finger, rng, size=size)


def drag(
    x1: int, y1: int, x2: int, y2: int, finger: int = 0, rng: random.Random | None = None,
    *, size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[Step]:
    """Curve to the end, brake, hold, then lift.

    One recorded drag bows a few pixels off the straight line and then stops.
    The bow, the timing, and the contact axes are drawn again on every call.
    The last point is the requested end.
    """
    rng = _rng(rng)
    travel = _frames(DRAG_BRAKE_MS * 2, DRAG_FRAME_JITTER * FRAME_MS, rng, minimum=8)
    hold_frames = _frames(DRAG_HOLD_MS, DRAG_HOLD_JITTER * FRAME_MS, rng, minimum=8)
    progress = _pace(
        travel,
        (rng.uniform(0.18, 0.38), rng.uniform(0.0, 0.12)),
        (rng.uniform(0.55, 0.78), rng.uniform(0.88, 1.0)),
    )
    points = _bow(x1, y1, x2, y2, progress, rng)
    points.extend([(x2, y2)] * hold_frames)
    ages = [FRAME_MS * i for i in range(len(points))]
    return _place(points, ages, finger, rng, size=size)


def long_press(
    x: int, y: int, ms: int, finger: int = 0, rng: random.Random | None = None,
    *, size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[Step]:
    """Hold near one point for about ``ms``, then lift.

    A recorded long press stayed on one sensor point while pressure climbed
    and the ellipse sat on one rung. The duration here stays near ``ms``.
    The point drifts a few pixels, pressure trends through the hold, and the
    ellipse steps once.
    """
    rng = _rng(rng)
    spread = max(40, int(round(ms * 0.08)))
    count = _frames(ms, spread, rng)
    reach = rng.uniform(2, HOLD_DRIFT_PX)
    heading = rng.random() * math.tau
    end = (x + reach * math.cos(heading), y + reach * math.sin(heading))
    bow = rng.uniform(0.5, 2.0)
    ctrl = (
        (x + end[0]) / 2 + bow * math.cos(heading + math.pi / 2),
        (y + end[1]) / 2 + bow * math.sin(heading + math.pi / 2),
    )
    progress = [i / count for i in range(count + 1)]
    points = []
    for i, t in enumerate(progress):
        if i == 0:
            points.append((x, y))
        else:
            px, py = _quad((x, y), ctrl, end, t)
            points.append((int(round(px)), int(round(py))))
    ages = [FRAME_MS * i for i in range(count + 1)]
    return _place(points, ages, finger, rng, size=size, wander=True)


def hold_drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    ms: int = HOLD_DRAG_MS,
    finger: int = 0,
    rng: random.Random | None = None,
    *,
    size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[Step]:
    """Hold near the start, then curve to the end without lifting.

    The finger stays down for the whole stroke. It rests near the start for
    about ``ms`` milliseconds (500 when omitted) and drifts a few pixels, then
    bows toward the requested end, settles there, and lifts. The duration
    stays near ``ms``. The last point is the requested end.
    """
    rng = _rng(rng)
    spread = max(HOLD_DRAG_MS_JITTER, int(round(ms * 0.08)))
    hold_count = _frames(ms, spread, rng)
    reach = rng.uniform(2, HOLD_DRIFT_PX)
    heading = rng.random() * math.tau
    drifted = (x1 + reach * math.cos(heading), y1 + reach * math.sin(heading))
    bow = rng.uniform(0.5, 2.0)
    ctrl = (
        (x1 + drifted[0]) / 2 + bow * math.cos(heading + math.pi / 2),
        (y1 + drifted[1]) / 2 + bow * math.sin(heading + math.pi / 2),
    )
    points: list[tuple[int, int]] = []
    for i in range(hold_count + 1):
        if i == 0:
            points.append((x1, y1))
        else:
            px, py = _quad((x1, y1), ctrl, drifted, i / hold_count)
            points.append((int(round(px)), int(round(py))))
    hx, hy = points[-1]
    length = math.hypot(x2 - hx, y2 - hy)
    travel_ms = int(
        round(
            min(HOLD_DRAG_MAX_TRAVEL_MS, max(HOLD_DRAG_MIN_TRAVEL_MS, length / 0.55))
        )
    )
    travel = _frames(travel_ms, 50, rng, minimum=8)
    progress = _pace(
        travel,
        (rng.uniform(0.18, 0.38), rng.uniform(0.0, 0.12)),
        (rng.uniform(0.55, 0.78), rng.uniform(0.88, 1.0)),
    )
    points.extend(_bow(hx, hy, x2, y2, progress, rng, amplitude=(8, 16))[1:])
    settle = _frames(HOLD_DRAG_SETTLE_MS, HOLD_DRAG_SETTLE_JITTER, rng, minimum=2)
    points.extend([(x2, y2)] * settle)
    ages = [FRAME_MS * i for i in range(len(points))]
    return _place(points, ages, finger, rng, size=size, wander=True)


def slow_drag(
    x1: int, y1: int, x2: int, y2: int, finger: int = 0, rng: random.Random | None = None,
    *, size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[Step]:
    """Curve to the end and lift while the point is still creeping.

    A recorded slow drag kept moving for the whole stroke and was down near
    115 px/s at the lift. There is no hold. The end point is the requested end.
    """
    rng = _rng(rng)
    length = math.hypot(x2 - x1, y2 - y1)
    end_speed = rng.uniform(80, 150)
    last_px = end_speed * FRAME_MS / 1000
    bend = rng.uniform(0.14, 0.28)
    count = int(round(bend * max(length, 1.0) / max(last_px, 0.4)))
    count = min(130, max(12, count))
    slope = min(0.85, max(0.05, last_px / max(length, 1.0) * count))
    points = _bow(x1, y1, x2, y2, _settle(count, slope, rng), rng)
    _keep_lift_moving(points)
    return _place(points, [FRAME_MS * i for i in range(len(points))], finger, rng, size=size)


def flick(
    x1: int, y1: int, x2: int, y2: int, finger: int = 0, rng: random.Random | None = None,
    *, size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[Step]:
    """Gain speed for about 250ms and lift while the point is still moving quickly.

    A recorded flick started near 170 px/s, reached about 11000 px/s over
    250ms on a 1000px stroke, and lifted on that last moving frame.
    """
    rng = _rng(rng)
    count = _frames(FLICK_RISE_MS, FLICK_MS_JITTER, rng, minimum=10)
    points = _bow(x1, y1, x2, y2, _rush(count, rng), rng, amplitude=(4, 16))
    return _place(points, [FRAME_MS * i for i in range(len(points))], finger, rng, size=size)


def pinch(
    cx: int, cy: int, start_gap: int, end_gap: int, rng: random.Random | None = None
) -> list[Step]:
    """Two fingers around one center.

    The caller gives the center and the two gaps, not the angle. A recorded
    pinch starts slowly, keeps moving until the lift, turns a few degrees,
    and the center drifts. Each call draws those again. The gaps at the
    first and last samples are the ones requested.
    """
    rng = _rng(rng)
    count = max(8, PINCH_MS // FRAME_MS + rng.randint(-8, 8))
    progress = _pace(
        count,
        (rng.uniform(0.20, 0.45), rng.uniform(0.0, 0.08)),
        (rng.uniform(0.55, 0.85), rng.uniform(0.62, 0.88)),
    )
    angle = rng.random() * math.tau
    spin = math.radians(rng.uniform(-14, 14))
    drift = rng.uniform(15, 60)
    drift_angle = rng.random() * math.tau
    bow = rng.uniform(8, 30)
    end = (cx + drift * math.cos(drift_angle), cy + drift * math.sin(drift_angle))
    ctrl = (
        (cx + end[0]) / 2 + bow * math.cos(drift_angle + math.pi / 2),
        (cy + end[1]) / 2 + bow * math.sin(drift_angle + math.pi / 2),
    )
    left_hump = rng.uniform(4, 24) * rng.choice((-1, 1))
    right_hump = rng.uniform(4, 24) * rng.choice((-1, 1))
    ages = [FRAME_MS * i for i in range(count + 1)]
    left_feel = _feel(ages, rng)
    right_feel = _feel(ages, rng)
    steps: list[Step] = []
    for i, t in enumerate(progress):
        gap = start_gap + (end_gap - start_gap) * t
        center = _quad((cx, cy), ctrl, end, t)
        facing = angle + spin * t
        hump = math.sin(math.pi * t)
        kind = Down if i == 0 else Move
        left, right = _finger_pair(center, facing, gap, hump, left_hump, right_hump)
        steps.append(_contact(kind, left[0], left[1], 0, left_feel[i]))
        steps.append(_contact(kind, right[0], right[1], 1, right_feel[i]))
        if i != count:
            steps.append(Sleep(ms=FRAME_MS))
    steps.append(Up(id=0))
    steps.append(Up(id=1))
    return steps


def _frames(ms: int, jitter: int, rng: random.Random, minimum: int = 2) -> int:
    """Frame count for a duration that may sit ``jitter`` ms to either side."""
    drawn = ms + rng.randint(-jitter, jitter)
    return max(minimum, round(drawn / FRAME_MS))


def _place(
    points: list[tuple[int, int]],
    ages: list[int],
    finger: int,
    rng: random.Random,
    *,
    size: tuple[int, int],
    wander: bool = False,
) -> list[Step]:
    width, height = size
    feel = _feel(ages, rng, wander=wander)
    steps: list[Step] = []
    for i, ((x, y), sample) in enumerate(zip(points, feel)):
        kind = Down if i == 0 else Move
        if i:
            steps.append(Sleep(ms=FRAME_MS))
        x = min(width - 1, max(0, x))
        y = min(height - 1, max(0, y))
        steps.append(_contact(kind, x, y, finger, sample))
    steps.append(Up(id=finger))
    return steps


def _feel(
    ages: list[int], rng: random.Random, wander: bool = False
) -> list[tuple[int, int, int, int]]:
    """Pressure, major, minor, and orientation for one finger.

    The center of the draw follows one recorded session. The spread is wider
    than that session, and each call draws again.
    """
    hold = rng.randint(480, 760)
    press_down = rng.randint(140, 380)
    press_up = rng.randint(120, 400)
    rise = rng.randint(50, 130)
    major = rng.randint(160, 250)
    minor = major - rng.randint(0, 40)
    shrink = rng.randint(24, 56)
    first_major = major - shrink
    first_minor = min(minor - shrink, first_major)
    facing = rng.randint(-70, 70)
    # A recorded long press climbed about 80 while it was held, and the
    # ellipse stayed on one rung until a single step.
    climb = rng.randint(-30, 80) if wander else 0
    rung = rng.choice((18, -19)) if wander else 0
    if wander and len(ages) >= 8:
        step_at = rng.randrange(max(2, len(ages) // 3), max(3, 2 * len(ages) // 3))
    else:
        step_at = len(ages)
    span = ages[-1] or 1
    samples = []
    last = len(ages) - 1
    for i, age in enumerate(ages):
        if len(ages) == 1:
            pressure = press_down
        elif i == last:
            # Land back in the press-down band, under the pressure reached so far.
            pressure = press_up if press_up < samples[-1][0] else press_down
        elif age >= rise:
            noise = rng.randint(-12, 12) if wander else rng.randint(-40, 40)
            pressure = hold + climb * age // span + noise
        else:
            pressure = press_down + (hold - press_down) * age // rise
        if i == 0:
            maj, mn = first_major, first_minor
        else:
            maj = major + (rung if i >= step_at else 0)
            mn = min(minor, maj)
        samples.append((pressure, maj, mn, facing + rng.randint(-12, 12)))
    return samples


def _contact(kind, x: int, y: int, finger: int, sample: tuple[int, int, int, int]):
    pressure, major, minor, orientation = sample
    return kind(
        x=x,
        y=y,
        id=finger,
        pressure=pressure,
        major=major,
        minor=minor,
        orientation=orientation,
    )


def _rng(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


def _keep_lift_moving(points: list[tuple[int, int]]) -> None:
    """Leave at least one pixel of travel into the last sample."""
    if len(points) < 2 or points[-1] != points[-2]:
        return
    x, y = points[-1]
    sx, sy = points[0]
    dx, dy = x - sx, y - sy
    norm = math.hypot(dx, dy) or 1.0
    nudged = (int(round(x - dx / norm)), int(round(y - dy / norm)))
    if nudged == (x, y):
        nudged = (x - 1 if x > 0 else x + 1, y)
    points[-2] = nudged


def _settle(count: int, slope: float, rng: random.Random) -> list[float]:
    """Progress that decelerates and is still moving at the last sample.

    ``slope`` is ds/du at the lift. The ease-out term has no speed left there,
    so the lift speed is the linear term.
    """
    power = rng.uniform(1.8, 2.6)
    samples = []
    for i in range(count + 1):
        u = i / count
        ease = 1 - (1 - u) ** power
        samples.append((1 - slope) * ease + slope * u)
    samples[0] = 0.0
    samples[-1] = 1.0
    return samples


def _rush(count: int, rng: random.Random) -> list[float]:
    """Progress that starts slow and is fastest on the last sample."""
    power = rng.uniform(2.7, 3.3)
    coast = rng.uniform(0.02, 0.045)
    return [(1 - coast) * (i / count) ** power + coast * (i / count) for i in range(count + 1)]


def _bow(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    progress: list[float],
    rng: random.Random,
    amplitude: tuple[int, int] = (8, 40),
) -> list[tuple[int, int]]:
    """One quadratic arc. Recorded strokes bow once and do not cross the chord."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    lo, hi = amplitude
    offset = rng.randint(lo, hi) * rng.choice((-1, 1))
    ctrl = ((x1 + x2) / 2 + nx * offset, (y1 + y2) / 2 + ny * offset)
    points = []
    last = len(progress) - 1
    for i, t in enumerate(progress):
        if i == 0:
            points.append((x1, y1))
        elif i == last:
            points.append((x2, y2))
        else:
            x, y = _quad((x1, y1), ctrl, (x2, y2), t)
            points.append((int(round(x)), int(round(y))))
    return points


def _finger_pair(
    center: tuple[float, float],
    facing: float,
    gap: float,
    hump: float,
    left_hump: float,
    right_hump: float,
) -> tuple[tuple[int, int], tuple[int, int]]:
    ux, uy = math.cos(facing), math.sin(facing)
    nx, ny = -uy, ux
    half = gap / 2
    left = (
        center[0] - ux * half + nx * left_hump * hump,
        center[1] - uy * half + ny * left_hump * hump,
    )
    right = (
        center[0] + ux * half + nx * right_hump * hump,
        center[1] + uy * half + ny * right_hump * hump,
    )
    return (int(round(left[0])), int(round(left[1]))), (
        int(round(right[0])),
        int(round(right[1])),
    )


def _pace(steps: int, start: tuple[float, float], end: tuple[float, float]) -> list[float]:
    """Progress along a stroke. 0 at the first sample and 1 at the last.

    ``start`` and ``end`` are the cubic Bezier handles of the timing curve.
    A drag handle arrives early and then creeps. A pinch handle is still
    moving at the lift.
    """

    def at(t: float, a: float, b: float) -> float:
        u = 1 - t
        return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t

    def slope(t: float, a: float, b: float) -> float:
        u = 1 - t
        return 3 * u * u * a + 6 * u * t * (b - a) + 3 * t * t * (1 - b)

    samples = []
    for i in range(steps + 1):
        target = i / steps
        t = target
        for _ in range(8):
            dx = slope(t, start[0], end[0])
            t -= (at(t, start[0], end[0]) - target) / (dx or 1e-6)
            t = min(1.0, max(0.0, t))
        samples.append(at(t, start[1], end[1]))
    samples[0] = 0.0
    samples[-1] = 1.0
    for i in range(1, len(samples)):
        if samples[i] < samples[i - 1]:
            samples[i] = samples[i - 1]
    return samples


def _quad(
    start: tuple[float, float], ctrl: tuple[float, float], end: tuple[float, float], t: float
) -> tuple[float, float]:
    u = 1 - t
    return (
        u * u * start[0] + 2 * u * t * ctrl[0] + t * t * end[0],
        u * u * start[1] + 2 * u * t * ctrl[1] + t * t * end[1],
    )
