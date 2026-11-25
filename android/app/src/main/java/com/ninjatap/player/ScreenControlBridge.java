package com.ninjatap.player;

import android.app.KeyguardManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.PowerManager;
import android.os.SystemClock;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;

final class ScreenControlBridge implements Closeable {
    private static final String SYSTEM_UI = "com.android.systemui";
    private static final String PIN_PROMPT = "/system/bin/dumpsys -t 1 activity service "
            + SYSTEM_UI + "/.SystemUIService NotificationShadeWindowControllerImpl"
            + " | grep -Eq 'mBouncerShowing:[[:space:]]*true([[:space:]]|$)'";
    private static final String NO_SIM_CHALLENGE = "/system/bin/dumpsys -t 1 window policy"
            + " | grep -Eq '^[[:space:]]*mSimSecure=false[[:space:]]*$'";
    final String name = "ninjatap-screen-" + UUID.randomUUID();

    private final LocalServerSocket listener = new LocalServerSocket(name);
    private final KeyguardManager keyguard;
    private final PowerManager power;
    private final ScreenPin pin;
    private final String helper;
    private final PackageManager packages;
    private final BooleanSupplier active;
    private final Thread worker;

    ScreenControlBridge(Context context, BooleanSupplier active) throws IOException {
        keyguard = context.getSystemService(KeyguardManager.class);
        power = context.getSystemService(PowerManager.class);
        pin = new ScreenPin(context);
        packages = context.getPackageManager();
        String apk = context.getApplicationInfo().sourceDir;
        helper = "CLASSPATH='" + apk.replace("'", "'\\''") + "' exec /system/bin/app_process /system/bin "
                + ScreenControlCli.class.getName();
        this.active = active;
        worker = new Thread(this::listen, "ninjatap-screen");
        worker.setDaemon(true);
        worker.start();
    }

    @Override
    public void close() throws IOException {
        worker.interrupt();
        try {
            Os.shutdown(listener.getFileDescriptor(), OsConstants.SHUT_RDWR);
        } catch (ErrnoException ignored) {
            // The listener may already have stopped accepting.
        } finally {
            listener.close();
        }
    }

    private void listen() {
        while (active.getAsBoolean() && !Thread.currentThread().isInterrupted()) {
            LocalSocket socket;
            try {
                socket = listener.accept();
            } catch (IOException closed) {
                return;
            }
            try (socket) {
                if (socket.getPeerCredentials().getUid() != 0) {
                    continue;
                }
                socket.setSoTimeout(1000);
                socket.getOutputStream().write('R');
                String result = switch (socket.getInputStream().read()) {
                    case 'L' -> control(false);
                    case 'U' -> control(true);
                    default -> "screen_control_failed";
                };
                socket.getOutputStream().write((result + "\n").getBytes(StandardCharsets.US_ASCII));
            } catch (IOException | RuntimeException ignored) {
                // The peer disconnected or the operation lost its Android service.
            } catch (InterruptedException stopped) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private String control(boolean unlock) throws InterruptedException {
        if (!active.getAsBoolean()) {
            return "screen_control_unavailable";
        }
        if (!unlock) {
            return lock();
        }
        try {
            return unlock();
        } catch (GeneralSecurityException | IOException | IllegalArgumentException error) {
            return "screen_pin_unavailable";
        }
    }

    private String lock() throws InterruptedException {
        ScreenCondition locked = () -> keyguard.isDeviceLocked() && !power.isInteractive();
        if (locked.ready()) {
            return "ok";
        }
        if ((!keyguard.isDeviceLocked() && !runRoot(helper + " lock", null))
                || (power.isInteractive() && !runRoot("/system/bin/input keyevent KEYCODE_SLEEP", null))) {
            return "screen_lock_failed";
        }
        return waitFor(locked, 2500) ? "ok" : "screen_lock_failed";
    }

    private String unlock()
            throws GeneralSecurityException, IOException, InterruptedException {
        if (isUnlocked()) {
            return "ok";
        }
        String saved = pin.saved();
        if (saved == null) {
            return "screen_pin_required";
        }
        if (pin.needsReset()) {
            return "screen_pin_reset_required";
        }
        int systemUiUid;
        try {
            systemUiUid = packages.getApplicationInfo(SYSTEM_UI, 0).uid;
        } catch (PackageManager.NameNotFoundException unavailable) {
            return "screen_pin_keypad_unavailable";
        }
        if (!keyguard.isDeviceSecure() || !runRoot(helper + " check " + systemUiUid, null)) {
            return "screen_pin_keypad_unavailable";
        }
        byte[] digits = pin.decrypt(saved);
        try {
            if (!waitFor(power::isInteractive, 2000)) {
                return "screen_wake_failed";
            }
            if (isUnlocked()) {
                return "ok";
            }
            if (runRoot(PIN_PROMPT, null)) {
                // Start with a fresh PIN prompt when a user has already opened one.
                if (!runRoot(helper + " back " + systemUiUid, null)
                        || !waitFor(() -> !runRoot(PIN_PROMPT, null), 800)) {
                    return "screen_pin_keypad_unavailable";
                }
            }
            // Window Manager opens the authentication screen while the device is securely locked.
            if (!runRoot("/system/bin/wm dismiss-keyguard", null)
                    || !waitFor(() -> isUnlocked() || runRoot(PIN_PROMPT, null), 2500)) {
                return "screen_pin_keypad_unavailable";
            }
            if (isUnlocked()) {
                return "ok";
            }
            if (!keyguard.isDeviceLocked() || !runRoot(NO_SIM_CHALLENGE, null)) {
                return "screen_pin_keypad_unavailable";
            }
            if (!active.getAsBoolean() || !pin.beginAttempt(saved)) {
                return "screen_control_unavailable";
            }
            boolean typed = runRoot(helper + " pin " + systemUiUid, digits);
            if (typed && !waitFor(this::isUnlocked, 650) && runRoot(PIN_PROMPT, null)) {
                runRoot(helper + " submit " + systemUiUid, null);
            }
            if (!waitFor(this::isUnlocked, 2500)) {
                return "screen_unlock_failed";
            }
            pin.confirmAttempt(saved);
            return "ok";
        } finally {
            Arrays.fill(digits, (byte) 0);
        }
    }

    private boolean isUnlocked() {
        return power.isInteractive() && !keyguard.isKeyguardLocked() && !keyguard.isDeviceLocked();
    }

    private boolean waitFor(ScreenCondition condition, long milliseconds) throws InterruptedException {
        long deadline = SystemClock.elapsedRealtime() + milliseconds;
        while (active.getAsBoolean()) {
            if (condition.ready()) {
                return true;
            }
            if (SystemClock.elapsedRealtime() >= deadline) {
                break;
            }
            Thread.sleep(80);
        }
        return false;
    }

    @FunctionalInterface
    private interface ScreenCondition {
        boolean ready() throws InterruptedException;
    }

    private boolean runRoot(String command, byte[] input) throws InterruptedException {
        if (!active.getAsBoolean()) {
            return false;
        }
        Process process;
        try {
            process = new ProcessBuilder("/system/bin/su", "-c", command)
                    .redirectErrorStream(true)
                    .redirectOutput(new File("/dev/null"))
                    .start();
        } catch (IOException unavailable) {
            return false;
        }
        try {
            try (var pipe = process.getOutputStream()) {
                if (input != null) {
                    pipe.write(input);
                }
            }
            return process.waitFor(2, TimeUnit.SECONDS) && process.exitValue() == 0;
        } catch (IOException unavailable) {
            return false;
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
            }
        }
    }
}
