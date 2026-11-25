package com.ninjatap.player;

import android.content.AttributionSource;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.os.Build;
import android.os.Looper;
import android.os.Process;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Read and write the clipboard as {@code com.android.shell}.
 *
 * Android only lets the focused app, the default IME, or a package holding
 * {@code READ_CLIPBOARD_IN_BACKGROUND} read the clipboard. Shell holds that
 * permission. This process must already be uid 2000.
 * createPackageContext leaves the attribution source as {@code android},
 * which uid 2000 does not own. The source has to name {@code com.android.shell}.
 */
public final class ClipboardCli {
    private static final int SHELL_UID = 2000;

    private ClipboardCli() {}

    public static void main(String[] args) {
        if (args.length < 1) {
            System.err.println("usage: ClipboardCli get|set [file]");
            System.exit(2);
        }
        try {
            if (Process.myUid() != SHELL_UID) {
                System.err.println("clipboard helper must run as shell, uid " + Process.myUid());
                System.exit(3);
            }
            Looper.prepareMainLooper();
            Context shell = shellContext();
            ClipboardManager clips = (ClipboardManager) shell.getSystemService(Context.CLIPBOARD_SERVICE);
            if ("get".equals(args[0])) {
                byte[] bytes = text(clips, shell).getBytes(StandardCharsets.UTF_8);
                System.out.write(bytes);
                System.out.flush();
                return;
            }
            if ("set".equals(args[0]) && args.length == 2) {
                byte[] bytes = Files.readAllBytes(Path.of(args[1]));
                String text = new String(bytes, StandardCharsets.UTF_8);
                clips.setPrimaryClip(ClipData.newPlainText("ninjatap", text));
                return;
            }
            System.err.println("usage: ClipboardCli get|set [file]");
            System.exit(2);
        } catch (Throwable error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static Context shellContext() throws Exception {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            throw new IllegalStateException("clipboard helper needs Android 12");
        }
        Class<?> thread = Class.forName("android.app.ActivityThread");
        Method systemMain = thread.getMethod("systemMain");
        Object activityThread = systemMain.invoke(null);
        Method getSystemContext = thread.getMethod("getSystemContext");
        Context system = (Context) getSystemContext.invoke(activityThread);
        Context shell = system.createPackageContext(
                "com.android.shell", Context.CONTEXT_IGNORE_SECURITY);
        AttributionSource source = new AttributionSource.Builder(Process.myUid())
                .setPackageName("com.android.shell")
                .build();
        setField(shell, "mAttributionSource", source);
        setField(shell, "mOpPackageName", "com.android.shell");
        return shell;
    }

    private static void setField(Object target, String name, Object value) throws Exception {
        Class<?> type = target.getClass();
        while (type != null) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                field.set(target, value);
                return;
            } catch (NoSuchFieldException ignored) {
                type = type.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name);
    }

    private static String text(ClipboardManager clips, Context context) {
        ClipData data = clips.getPrimaryClip();
        if (data == null || data.getItemCount() == 0) {
            return "";
        }
        CharSequence value = data.getItemAt(0).coerceToText(context);
        return value == null ? "" : value.toString();
    }
}
