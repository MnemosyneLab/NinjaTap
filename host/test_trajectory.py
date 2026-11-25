"""Checks for the pixel trajectories."""

import math
import random
import unittest

from ninjatap.protocol import Down, Move, Sleep, Up
from ninjatap.trajectory import (
    DRAG_HOLD_MS,
    FLICK_MS_JITTER,
    FLICK_RISE_MS,
    FRAME_MS,
    HOLD_DRAG_MAX_TRAVEL_MS,
    HOLD_DRAG_MS,
    HOLD_DRAG_MS_JITTER,
    HOLD_DRAG_SETTLE_JITTER,
    HOLD_DRAG_SETTLE_MS,
    TAP_JITTER,
    TAP_MS,
    TAP_MS_JITTER,
    drag,
    flick,
    hold_drag,
    long_press,
    pinch,
    slow_drag,
    tap,
)


class TrajectoryTest(unittest.TestCase):
    def test_tap_stays_on_one_point_for_about_60ms(self):
        steps = tap(632, 1500, rng=random.Random(1))
        self.assertIsInstance(steps[0], Down)
        self.assertIsInstance(steps[-1], Up)
        sleeps = [step.ms for step in steps if isinstance(step, Sleep)]
        self.assertLessEqual(abs(sum(sleeps) - TAP_MS), TAP_MS_JITTER + FRAME_MS)
        durations = {
            sum(step.ms for step in tap(632, 1500, rng=random.Random(seed)) if isinstance(step, Sleep))
            for seed in range(8)
        }
        self.assertGreater(len(durations), 1)
        points = [(step.x, step.y) for step in steps if isinstance(step, (Down, Move))]
        self.assertGreater(len(points), 1)
        self.assertEqual(len(set(points)), 1)
        x, y = points[0]
        self.assertLessEqual(abs(x - 632), TAP_JITTER)
        self.assertLessEqual(abs(y - 1500), TAP_JITTER)
        for seed in range(8):
            pressures = [
                step.pressure
                for step in tap(632, 1500, rng=random.Random(seed))
                if isinstance(step, (Down, Move))
            ]
            self.assertLess(pressures[-1], max(pressures[:-1]))

    def test_drag_bows_brakes_then_holds_the_end(self):
        steps = drag(420, 1400, 860, 1900, rng=random.Random(1))
        points = [(step.x, step.y) for step in steps if isinstance(step, (Down, Move))]
        self.assertEqual(points[0], (420, 1400))
        self.assertEqual(points[-1], (860, 1900))
        hold = 0
        while hold < len(points) and points[-1 - hold] == (860, 1900):
            hold += 1
        self.assertGreaterEqual(hold, DRAG_HOLD_MS // FRAME_MS - 6)
        travel = points[: len(points) - hold + 1]
        self.assertGreaterEqual(_off_line(travel), 3)
        sizes = _steps(travel)
        self.assertGreater(max(sizes), max(sizes[-6:]))
        self.assertGreater(max(sizes), min(sizes) * 2)
        self.assertIsInstance(steps[-1], Up)
        self.assertNotEqual(
            _points(drag(420, 1400, 860, 1900)),
            _points(drag(420, 1400, 860, 1900)),
        )
        self.assertNotEqual(_sleep_sum(drag(420, 1400, 860, 1900, rng=random.Random(1))), _sleep_sum(drag(420, 1400, 860, 1900, rng=random.Random(4))))

    def test_hold_drag_rests_then_moves_without_lifting(self):
        steps = hold_drag(400, 800, 900, 1600, rng=random.Random(1))
        points = _points(steps)
        ups = [step for step in steps if isinstance(step, Up)]
        self.assertEqual(len(ups), 1)
        self.assertIsInstance(steps[0], Down)
        self.assertIsInstance(steps[-1], Up)
        self.assertEqual(points[0], (400, 800))
        self.assertEqual(points[-1], (900, 1600))
        near = 0
        for x, y in points:
            if math.hypot(x - 400, y - 800) > 6:
                break
            near += 1
        self.assertGreaterEqual((near - 1) * FRAME_MS, HOLD_DRAG_MS - HOLD_DRAG_MS_JITTER)
        self.assertLess((near - 1) * FRAME_MS, HOLD_DRAG_MS + HOLD_DRAG_MS_JITTER + 12 * FRAME_MS)
        self.assertTrue(any(point != points[0] for point in points[:near]))
        settle = 0
        while settle < len(points) and points[-1 - settle] == (900, 1600):
            settle += 1
        extra_ms = (settle - 1) * FRAME_MS
        self.assertLessEqual(
            abs(extra_ms - HOLD_DRAG_SETTLE_MS), HOLD_DRAG_SETTLE_JITTER + FRAME_MS
        )
        self.assertLess(settle * FRAME_MS, DRAG_HOLD_MS)
        travel = points[near - 1 : len(points) - settle + 1]
        self.assertGreater(len(travel), 8)
        self.assertGreaterEqual(_off_line(travel), 3)
        self.assertLess(_sleep_sum(steps), HOLD_DRAG_MS + HOLD_DRAG_MAX_TRAVEL_MS + HOLD_DRAG_SETTLE_MS + 200)
        self.assertEqual(
            hold_drag(400, 800, 900, 1600, rng=random.Random(3)),
            hold_drag(400, 800, 900, 1600, rng=random.Random(3)),
        )
        self.assertNotEqual(
            _sleep_sum(hold_drag(400, 800, 900, 1600, rng=random.Random(1))),
            _sleep_sum(hold_drag(400, 800, 900, 1600, rng=random.Random(2))),
        )

    def test_hold_drag_rest_follows_the_requested_duration(self):
        ms = 1200
        steps = hold_drag(400, 800, 900, 1600, ms=ms, rng=random.Random(1))
        points = _points(steps)
        near = 0
        for x, y in points:
            if math.hypot(x - 400, y - 800) > 6:
                break
            near += 1
        spread = max(HOLD_DRAG_MS_JITTER, int(round(ms * 0.08)))
        rest = (near - 1) * FRAME_MS
        self.assertGreaterEqual(rest, ms - spread)
        self.assertLess(rest, ms + spread + 12 * FRAME_MS)
        self.assertEqual(len([step for step in steps if isinstance(step, Up)]), 1)
        self.assertEqual(points[-1], (900, 1600))

    def test_slow_drag_lifts_while_still_creeping(self):
        steps = slow_drag(100, 400, 1100, 400, rng=random.Random(1))
        points = _points(steps)
        self.assertEqual(points[0], (100, 400))
        self.assertEqual(points[-1], (1100, 400))
        self.assertEqual(points.count(points[-1]), 1)
        self.assertGreater(_sleep_sum(steps), 800)
        self.assertLess(_sleep_sum(steps), 2300)
        sizes = _steps(points)
        end_speed = sizes[-1] / (FRAME_MS / 1000)
        self.assertGreater(end_speed, 40)
        self.assertLess(end_speed, 280)
        self.assertGreater(max(sizes), sizes[-1] * 2)
        self.assertGreater(_off_line(points), 3)
        self.assertIsInstance(steps[-1], Up)
        durations = {
            _sleep_sum(slow_drag(100, 400, 1100, 400, rng=random.Random(seed)))
            for seed in range(8)
        }
        self.assertGreater(len(durations), 1)

    def test_flick_accelerates_and_lifts_while_moving_quickly(self):
        steps = flick(100, 800, 1100, 800, rng=random.Random(1))
        points = _points(steps)
        self.assertEqual(points[0], (100, 800))
        self.assertEqual(points[-1], (1100, 800))
        self.assertEqual(points.count(points[-1]), 1)
        self.assertLessEqual(abs(_sleep_sum(steps) - FLICK_RISE_MS), FLICK_MS_JITTER + FRAME_MS)
        sizes = _steps(points)
        self.assertGreater(sizes[-1], sizes[0] * 8)
        end_speed = sizes[-1] / (FRAME_MS / 1000)
        self.assertGreater(end_speed, 6000)
        self.assertLess(end_speed, 16000)
        self.assertGreater(max(sizes), sizes[0])
        self.assertEqual(sizes.index(max(sizes)), len(sizes) - 1)
        self.assertIsInstance(steps[-1], Up)
        durations = {
            _sleep_sum(flick(100, 800, 1100, 800, rng=random.Random(seed))) for seed in range(8)
        }
        self.assertGreater(len(durations), 1)

    def test_pinch_changes_the_gap_off_the_horizontal(self):
        steps = pinch(632, 1600, 560, 180, rng=random.Random(2))
        pairs = _pairs(steps)
        self.assertAlmostEqual(_gap(pairs[0][0], pairs[0][1]), 560, delta=1.5)
        self.assertAlmostEqual(_gap(pairs[-1][0], pairs[-1][1]), 180, delta=1.5)
        self.assertLess(_mid(pairs[0], 632, 1600), 1.5)
        self.assertGreater(_mid(pairs[-1], 632, 1600), 10)
        angles = [_angle(left, right) for left, right in pairs]
        self.assertGreater(max(angles) - min(angles), math.radians(1))
        gaps = [_gap(left, right) for left, right in pairs]
        gap_steps = [abs(b - a) for a, b in zip(gaps, gaps[1:])]
        self.assertGreater(max(gap_steps), min(gap_steps) * 2)
        other = pinch(632, 1600, 560, 180, rng=random.Random(5))
        self.assertNotAlmostEqual(_angle(*_pairs(other)[0]), angles[0], delta=0.2)
        ups = [step.id for step in steps if isinstance(step, Up)]
        self.assertEqual(ups, [0, 1])
        body = steps[: steps.index(next(step for step in steps if isinstance(step, Up)))]
        self.assertEqual(len(body) % 3, 2)
        self.assertTrue(all(isinstance(step, Sleep) for step in body[2::3]))

    def test_long_press_drifts_near_the_point_for_about_the_requested_time(self):
        ms = 1000
        steps = long_press(632, 1500, ms, rng=random.Random(1))
        points = _points(steps)
        self.assertEqual(points[0], (632, 1500))
        self.assertTrue(any(point != points[0] for point in points))
        self.assertTrue(all(math.hypot(x - 632, y - 1500) <= 6 for x, y in points))
        self.assertLessEqual(abs(_sleep_sum(steps) - ms), max(40, int(ms * 0.08)) + FRAME_MS)
        contacts = [step for step in steps if isinstance(step, (Down, Move))]
        pressures = [step.pressure for step in contacts]
        self.assertLess(pressures[0], max(pressures[1:-1]))
        self.assertLess(pressures[-1], max(pressures[1:-1]))
        self.assertGreater(max(pressures[1:-1]) - min(pressures[1:-1]), 20)
        self.assertNotEqual(contacts[1].major, contacts[-1].major)
        self.assertTrue(all(step.minor <= step.major for step in contacts))
        self.assertNotEqual(
            _sleep_sum(long_press(632, 1500, ms, rng=random.Random(1))),
            _sleep_sum(long_press(632, 1500, ms, rng=random.Random(2))),
        )
        self.assertEqual(
            long_press(632, 1500, ms, rng=random.Random(3)),
            long_press(632, 1500, ms, rng=random.Random(3)),
        )

    def test_contact_rises_holds_and_drops_and_two_calls_differ(self):
        steps = drag(420, 1400, 860, 1900, rng=random.Random(1))
        contacts = [step for step in steps if isinstance(step, (Down, Move))]
        pressures = [step.pressure for step in contacts]
        self.assertLess(pressures[0], max(pressures[1:-1]))
        self.assertLess(pressures[-1], max(pressures[1:-1]))
        self.assertLess(contacts[0].major, contacts[1].major)
        self.assertEqual(contacts[-1].major, contacts[1].major)
        self.assertTrue(all(step.minor <= step.major for step in contacts))
        orientations = [step.orientation for step in contacts]
        self.assertLessEqual(max(orientations) - min(orientations), 24)
        self.assertGreater(abs(contacts[-1].y - contacts[0].y), 100)
        again = drag(420, 1400, 860, 1900)
        third = drag(420, 1400, 860, 1900)
        self.assertNotEqual(_contact_axes(again), _contact_axes(third))

    def test_the_same_seed_repeats_and_pinch_fingers_differ(self):
        self.assertEqual(tap(632, 1500, rng=random.Random(3)), tap(632, 1500, rng=random.Random(3)))
        self.assertEqual(
            drag(420, 1400, 860, 1900, rng=random.Random(3)),
            drag(420, 1400, 860, 1900, rng=random.Random(3)),
        )
        self.assertEqual(
            pinch(632, 1600, 560, 180, rng=random.Random(3)),
            pinch(632, 1600, 560, 180, rng=random.Random(3)),
        )
        self.assertEqual(
            slow_drag(100, 400, 1100, 400, rng=random.Random(3)),
            slow_drag(100, 400, 1100, 400, rng=random.Random(3)),
        )
        self.assertEqual(
            flick(100, 800, 1100, 800, rng=random.Random(3)),
            flick(100, 800, 1100, 800, rng=random.Random(3)),
        )
        steps = pinch(632, 1600, 560, 180, rng=random.Random(2))
        left = _contact_axes(step for step in steps if getattr(step, "id", None) == 0)
        right = _contact_axes(step for step in steps if getattr(step, "id", None) == 1)
        self.assertNotEqual(left, right)
        contacts = [step for step in steps if isinstance(step, (Down, Move))]
        self.assertTrue(all(step.minor <= step.major for step in contacts))


def _contact_axes(steps):
    return [
        (step.pressure, step.major, step.minor, step.orientation)
        for step in steps
        if isinstance(step, (Down, Move))
    ]


def _sleep_sum(steps):
    return sum(step.ms for step in steps if isinstance(step, Sleep))


def _points(steps):
    return [(step.x, step.y) for step in steps if isinstance(step, (Down, Move))]


def _pairs(steps):
    contacts = [step for step in steps if isinstance(step, (Down, Move))]
    return list(zip(contacts[0::2], contacts[1::2]))


def _steps(points):
    return [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]


def _off_line(points):
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    return max(abs((x - x1) * dy - (y - y1) * dx) / length for x, y in points)


def _gap(left, right):
    return math.hypot(right.x - left.x, right.y - left.y)


def _angle(left, right):
    return math.atan2(right.y - left.y, right.x - left.x)


def _mid(pair, cx, cy):
    left, right = pair
    return math.hypot((left.x + right.x) / 2 - cx, (left.y + right.y) / 2 - cy)


if __name__ == "__main__":
    unittest.main()
