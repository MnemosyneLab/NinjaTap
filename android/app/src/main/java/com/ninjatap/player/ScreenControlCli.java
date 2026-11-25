package com.ninjatap.player;

import android.os.Bundle;
import android.os.IBinder;
import android.os.Process;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;

import java.io.DataInputStream;
import java.lang.reflect.Method;
import java.util.Arrays;

/** Root-only helper launched with app_process. The PIN is read from a private pipe. */
public final class ScreenControlCli {
    private static final int WAIT_FOR_FINISH = 2;
    private static final String WINDOW_MANAGER = "android.view.IWindowManager";
    private static final String LOCK_SETTINGS = "com.android.internal.widget.ILockSettings";

    private ScreenControlCli() {}

    public static void main(String[] args) {
        try {
            System.exit(Process.myUid() == 0 && run(args) ? 0 : 1);
        } catch (Exception error) {
            System.exit(1);
        }
    }

    private static boolean run(String[] args) throws Exception {
        if (args.length == 1 && "lock".equals(args[0])) {
            Class.forName(WINDOW_MANAGER).getMethod("lockNow", Bundle.class)
                    .invoke(service("window", WINDOW_MANAGER), (Bundle) null);
            return true;
        }
        if (args.length != 2) {
            return false;
        }
        int systemUiUid = Integer.parseInt(args[1]);
        // NinjaTap runs on the owner user. Accept only that user's SystemUI target.
        if (systemUiUid < 10000 || systemUiUid >= 100000 || !ownerHasPin()) {
            return false;
        }
        if ("check".equals(args[0])) {
            return true;
        }
        Class<?> managerClass = Class.forName("android.hardware.input.InputManagerGlobal");
        Object manager = managerClass.getMethod("getInstance").invoke(null);
        Method inject = managerClass.getMethod("injectInputEvent", InputEvent.class, int.class, int.class);
        if ("submit".equals(args[0])) {
            return press(manager, inject, systemUiUid, KeyEvent.KEYCODE_ENTER);
        }
        if ("back".equals(args[0])) {
            return press(manager, inject, systemUiUid, KeyEvent.KEYCODE_BACK);
        }
        if (!"pin".equals(args[0])) {
            return false;
        }
        byte[] digits = new byte[ScreenPin.LENGTH];
        try {
            new DataInputStream(System.in).readFully(digits);
            for (byte digit : digits) {
                if (digit < '0' || digit > '9') {
                    return false;
                }
            }
            for (byte digit : digits) {
                if (!press(manager, inject, systemUiUid, KeyEvent.KEYCODE_0 + digit - '0')) {
                    return false;
                }
            }
            return true;
        } finally {
            Arrays.fill(digits, (byte) 0);
        }
    }

    private static boolean ownerHasPin() throws Exception {
        int currentUser = (int) Class.forName("android.app.ActivityManager")
                .getMethod("getCurrentUser").invoke(null);
        int credentialType = (int) Class.forName(LOCK_SETTINGS).getMethod("getCredentialType", int.class)
                .invoke(service("lock_settings", LOCK_SETTINGS), currentUser);
        int pinType = Class.forName("com.android.internal.widget.LockPatternUtils")
                .getField("CREDENTIAL_TYPE_PIN").getInt(null);
        return currentUser == 0 && credentialType == pinType;
    }

    private static Object service(String name, String interfaceName) throws Exception {
        IBinder binder = (IBinder) Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class).invoke(null, name);
        return Class.forName(interfaceName + "$Stub").getMethod("asInterface", IBinder.class)
                .invoke(null, binder);
    }

    private static boolean press(Object manager, Method inject, int targetUid, int key) throws Exception {
        long down = SystemClock.uptimeMillis();
        KeyEvent press = new KeyEvent(down, down, KeyEvent.ACTION_DOWN, key, 0, 0,
                KeyCharacterMap.VIRTUAL_KEYBOARD, 0, 0, InputDevice.SOURCE_KEYBOARD);
        if (!(boolean) inject.invoke(manager, press, WAIT_FOR_FINISH, targetUid)) {
            return false;
        }
        KeyEvent release = KeyEvent.changeAction(press, KeyEvent.ACTION_UP);
        return (boolean) inject.invoke(manager, release, WAIT_FOR_FINISH, targetUid);
    }
}
