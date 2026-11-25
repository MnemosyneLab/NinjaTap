package com.ninjatap.inject;

import android.system.Os;
import java.io.FileDescriptor;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

import static android.system.OsConstants.O_WRONLY;

/** Writes one gesture to the DNY-NX9 touchscreen node. */
public class Inject {
    static final String DEVICE = "/dev/input/event6";
    static final int SCALE = 8;
    static final int PRESSURE = 600;
    static final int TOUCH_MAJOR = 205;
    static final int TOUCH_MINOR = 186;

    static final int EV_SYN = 0;
    static final int EV_KEY = 1;
    static final int EV_ABS = 3;
    static final int SYN_REPORT = 0;
    static final int SYN_MT_REPORT = 2;
    static final int BTN_TOUCH = 0x14a;
    static final int ABS_MT_TOUCH_MAJOR = 0x30;
    static final int ABS_MT_TOUCH_MINOR = 0x31;
    static final int ABS_MT_POSITION_X = 0x35;
    static final int ABS_MT_POSITION_Y = 0x36;
    static final int ABS_MT_TRACKING_ID = 0x39;
    static final int ABS_MT_PRESSURE = 0x3a;

    static FileDescriptor fd;

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            throw new IllegalArgumentException("usage: tap|drag|pinch ...");
        }
        fd = Os.open(DEVICE, O_WRONLY, 0);
        try {
            String cmd = args[0];
            if (cmd.equals("tap")) {
                tap(num(args, 1), num(args, 2));
            } else if (cmd.equals("drag")) {
                drag(num(args, 1), num(args, 2), num(args, 3), num(args, 4), num(args, 5), num(args, 6));
            } else if (cmd.equals("pinch")) {
                pinch(num(args, 1), num(args, 2), num(args, 3), num(args, 4), num(args, 5), num(args, 6));
            } else {
                throw new IllegalArgumentException(cmd);
            }
            System.out.println("ok " + cmd + " pressure " + PRESSURE
                    + " major " + TOUCH_MAJOR + " minor " + TOUCH_MINOR);
        } finally {
            lift();
            Os.close(fd);
        }
    }

    static void tap(int x, int y) throws Exception {
        frame(new int[][]{{0, x, y}}, true);
        sleep(17);
        frame(new int[][]{{0, x, y}}, false);
        sleep(17);
        frame(new int[][]{{0, x, y}}, false);
        sleep(17);
    }

    static void drag(int x1, int y1, int x2, int y2, int steps, int stepMs) throws Exception {
        frame(new int[][]{{0, x1, y1}}, true);
        sleep(40);
        for (int i = 1; i <= steps; i++) {
            int x = x1 + (x2 - x1) * i / steps;
            int y = y1 + (y2 - y1) * i / steps;
            frame(new int[][]{{0, x, y}}, false);
            sleep(stepMs);
        }
        sleep(80);
    }

    static void pinch(int cx, int cy, int r0, int r1, int steps, int stepMs) throws Exception {
        for (int i = 0; i <= steps; i++) {
            int r = r0 + (r1 - r0) * i / steps;
            frame(new int[][]{
                    {0, cx - r, cy},
                    {1, cx + r, cy}
            }, i == 0);
            sleep(i == 0 ? 40 : stepMs);
        }
        sleep(80);
    }

    static void frame(int[][] points, boolean down) throws Exception {
        for (int[] p : points) {
            ev(EV_ABS, ABS_MT_TRACKING_ID, p[0]);
            ev(EV_ABS, ABS_MT_POSITION_X, p[1] * SCALE);
            ev(EV_ABS, ABS_MT_POSITION_Y, p[2] * SCALE);
            ev(EV_ABS, ABS_MT_PRESSURE, PRESSURE);
            ev(EV_ABS, ABS_MT_TOUCH_MAJOR, TOUCH_MAJOR);
            ev(EV_ABS, ABS_MT_TOUCH_MINOR, TOUCH_MINOR);
            ev(EV_SYN, SYN_MT_REPORT, 0);
        }
        if (down) {
            ev(EV_KEY, BTN_TOUCH, 1);
        }
        ev(EV_SYN, SYN_REPORT, 0);
    }

    static void lift() throws Exception {
        ev(EV_SYN, SYN_MT_REPORT, 0);
        ev(EV_KEY, BTN_TOUCH, 0);
        ev(EV_SYN, SYN_REPORT, 0);
    }

    static void ev(int type, int code, int value) throws Exception {
        ByteBuffer buf = ByteBuffer.allocate(24).order(ByteOrder.LITTLE_ENDIAN);
        long now = System.currentTimeMillis();
        buf.putLong(now / 1000L);
        buf.putLong((now % 1000L) * 1000L);
        buf.putShort((short) type);
        buf.putShort((short) code);
        buf.putInt(value);
        int n = Os.write(fd, buf.array(), 0, 24);
        if (n != 24) {
            throw new IllegalStateException("short write " + n);
        }
    }

    static void sleep(int ms) throws InterruptedException {
        Thread.sleep(ms);
    }

    static int num(String[] args, int i) {
        return Integer.parseInt(args[i]);
    }
}
