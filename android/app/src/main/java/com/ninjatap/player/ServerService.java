package com.ninjatap.player;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.MediaScannerConnection;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;

import org.json.JSONException;
import org.json.JSONTokener;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

public final class ServerService extends Service {
    public static final String ACTION_START = "com.ninjatap.player.START";
    public static final String ACTION_STOP = "com.ninjatap.player.STOP";

    private static final String EXTRA_BIND = "bind";
    private static final String EXTRA_PORT = "port";
    private static final String EXTRA_TOKEN = "token";
    private static final String EXTRA_REACHABLE = "reachable";
    private static final String CHANNEL_ID = "ninjatap";
    private static final int NOTIFICATION_ID = 1;

    private static final List<Listener> LISTENERS = new CopyOnWriteArrayList<>();
    private static volatile State current = State.stopped();

    private final AtomicInteger generation = new AtomicInteger();
    private volatile Process server;

    public static State current() {
        return current;
    }

    public static void addListener(Listener listener) {
        LISTENERS.add(listener);
    }

    public static void removeListener(Listener listener) {
        LISTENERS.remove(listener);
    }

    public static void start(Context context, String bind, int port, String token, String reachable) {
        Intent intent = new Intent(context, ServerService.class);
        intent.setAction(ACTION_START);
        intent.putExtra(EXTRA_BIND, bind);
        intent.putExtra(EXTRA_PORT, port);
        intent.putExtra(EXTRA_TOKEN, token);
        intent.putExtra(EXTRA_REACHABLE, reachable);
        ContextCompat.startForegroundService(context, intent);
    }

    public static void stop(Context context) {
        Intent intent = new Intent(context, ServerService.class);
        intent.setAction(ACTION_STOP);
        context.startService(intent);
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            halt(false);
            return START_NOT_STICKY;
        }
        String bind = intent == null ? "" : intent.getStringExtra(EXTRA_BIND);
        int port = intent == null ? 0 : intent.getIntExtra(EXTRA_PORT, 0);
        String token = intent == null ? "" : intent.getStringExtra(EXTRA_TOKEN);
        String reachable = intent == null ? "" : intent.getStringExtra(EXTRA_REACHABLE);
        enterForeground(getString(R.string.status_starting));
        publish(State.startingState());
        int ticket = generation.incrementAndGet();
        new Thread(() -> launch(ticket, bind, port, token == null ? "" : token, reachable), "ninjatap-start")
                .start();
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        halt(true);
        super.onDestroy();
    }

    private void launch(int ticket, String bind, int port, String token, String reachable) {
        try {
            runSu("kill $(pidof ninjatap) >/dev/null 2>&1; rm -f /data/local/tmp/ninjatap.pid; exit 0");
            installBinary();
            if (ticket != generation.get()) {
                return;
            }
            File identity = new File(getNoBackupFilesDir(), "ninjatap-identity.pem");
            String command = "echo $$ >/data/local/tmp/ninjatap.pid; "
                    + "export NINJATAP_BIND=" + quote(bind + ":" + port) + "; "
                    + "export NINJATAP_SECRET=" + quote(token) + "; "
                    + "export NINJATAP_TLS_IDENTITY=" + quote(identity.getAbsolutePath()) + "; "
                    + "exec /data/local/tmp/ninjatap";
            Process process = new ProcessBuilder("/system/bin/su", "-c", command).start();
            StringBuilder log = new StringBuilder();
            pump(process.getErrorStream(), log);
            server = process;
            String fingerprint = awaitFingerprint(process, log, ticket);
            if (ticket != generation.get()) {
                process.destroy();
                return;
            }
            String where = "https://" + (reachable == null || reachable.isEmpty() ? bind : reachable) + ":" + port;
            String status = getString(R.string.status_listening, where);
            enterForeground(status);
            publish(new State(true, false, where, fingerprint, ""));
            process.waitFor();
            if (ticket == generation.get()) {
                String detail = logText(log);
                fail(detail.isEmpty() ? "播放进程已退出" : detail);
            }
        } catch (Exception error) {
            if (ticket == generation.get()) {
                String message = error.getMessage() == null ? "启动失败" : error.getMessage();
                if (message.contains("error=2") || message.contains("No such file")) {
                    message = "请先在 KernelSU 里允许 NinjaTap 的 root。允许之后如果应用还开着，划掉再打开，然后点开启。";
                }
                Log.w("NinjaTap", message, error);
                fail(message);
            }
        }
    }

    private String awaitFingerprint(Process process, StringBuilder log, int ticket) throws Exception {
        CompletableFuture<String> ready = new CompletableFuture<>();
        Thread reader = new Thread(() -> {
            try (BufferedReader lines = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = lines.readLine()) != null) {
                    if (line.matches("NINJATAP_READY [0-9a-f]{64}")) {
                        ready.complete(line.substring("NINJATAP_READY ".length()));
                    } else if (line.startsWith("NINJATAP_SCAN ") && ticket == generation.get()) {
                        scanUploadedFile(line.substring("NINJATAP_SCAN ".length()));
                    }
                }
            } catch (IOException error) {
                ready.completeExceptionally(error);
            } finally {
                ready.complete(null);
            }
        }, "ninjatap-player-output");
        reader.setDaemon(true);
        reader.start();
        try {
            String fingerprint = ready.get(5, TimeUnit.SECONDS);
            if (fingerprint != null) {
                return fingerprint;
            }
            String detail = logText(log);
            throw new IOException(detail.isEmpty() ? "播放进程未启动 HTTPS" : detail);
        } catch (TimeoutException error) {
            throw new IOException("等待 HTTPS 服务启动超时", error);
        }
    }

    private void scanUploadedFile(String encodedPath) {
        try {
            Object value = new JSONTokener(encodedPath).nextValue();
            if (value instanceof String path && path.startsWith("/storage/emulated/0/")) {
                MediaScannerConnection.scanFile(this, new String[] {path}, null, null);
            }
        } catch (JSONException | RuntimeException error) {
            Log.w("NinjaTap", "Could not index an uploaded file", error);
        }
    }

    private void halt(boolean destroying) {
        generation.incrementAndGet();
        Process process = server;
        server = null;
        if (process != null) {
            process.destroy();
        }
        try {
            runSu("kill $(pidof ninjatap) >/dev/null 2>&1; rm -f /data/local/tmp/ninjatap.pid; exit 0");
        } catch (Exception ignored) {
            // Stopping still clears the notification when su is unavailable.
        }
        if (!destroying || current.running() || current.starting()) {
            publish(State.stopped());
        }
        stopForeground(STOP_FOREGROUND_REMOVE);
        if (!destroying) {
            stopSelf();
        }
    }

    private void fail(String detail) {
        publish(new State(false, false, "", "", detail.trim()));
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void installBinary() throws IOException, InterruptedException {
        Process process = new ProcessBuilder(
                "/system/bin/su", "-c", "cat >/data/local/tmp/ninjatap && chmod 755 /data/local/tmp/ninjatap")
                .start();
        ByteArrayOutputStream errors = new ByteArrayOutputStream();
        Thread drain = drainTo(process.getErrorStream(), errors);
        try (InputStream asset = getAssets().open("ninjatap")) {
            asset.transferTo(process.getOutputStream());
        } finally {
            process.getOutputStream().close();
        }
        int code = process.waitFor();
        drain.join();
        if (code != 0) {
            String detail = errors.toString(StandardCharsets.UTF_8).trim();
            throw new IOException(detail.isEmpty() ? "su 退出 " + code : detail);
        }
    }

    private static SuResult runSu(String command) throws IOException, InterruptedException {
        Process process = new ProcessBuilder("/system/bin/su", "-c", command).start();
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        Thread drain = drainTo(process.getInputStream(), output);
        ByteArrayOutputStream errors = new ByteArrayOutputStream();
        Thread err = drainTo(process.getErrorStream(), errors);
        int code = process.waitFor();
        drain.join();
        err.join();
        String text = (output.toString(StandardCharsets.UTF_8) + errors.toString(StandardCharsets.UTF_8)).trim();
        return new SuResult(code, text);
    }

    private static Thread drainTo(InputStream input, ByteArrayOutputStream sink) {
        Thread thread = new Thread(() -> {
            try {
                input.transferTo(sink);
            } catch (IOException ignored) {
                // The process closed the stream.
            }
        });
        thread.setDaemon(true);
        thread.start();
        return thread;
    }

    private void pump(InputStream input, StringBuilder log) {
        Thread thread = new Thread(() -> {
            byte[] buffer = new byte[1024];
            try {
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    synchronized (log) {
                        log.append(new String(buffer, 0, count, StandardCharsets.UTF_8));
                        if (log.length() > 4000) {
                            log.delete(0, log.length() - 4000);
                        }
                    }
                }
            } catch (IOException ignored) {
                // The player closed its output.
            }
        });
        thread.setDaemon(true);
        thread.start();
    }

    private static String logText(StringBuilder log) {
        synchronized (log) {
            return log.toString().trim();
        }
    }

    private void enterForeground(String text) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW);
            manager.createNotificationChannel(channel);
        }
        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(text)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private static void publish(State state) {
        current = state;
        for (Listener listener : LISTENERS) {
            listener.onState(state);
        }
    }

    private static String quote(String value) {
        return "'" + value.replace("'", "'\\''") + "'";
    }

    public interface Listener {
        void onState(State state);
    }

    public record State(boolean running, boolean starting, String url, String fingerprint, String error) {
        static State stopped() {
            return new State(false, false, "", "", "");
        }

        static State startingState() {
            return new State(false, true, "", "", "");
        }
    }

    private record SuResult(int code, String text) {}
}
