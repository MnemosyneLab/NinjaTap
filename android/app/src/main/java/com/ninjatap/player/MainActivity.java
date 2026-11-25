package com.ninjatap.player;

import android.Manifest;
import android.content.ClipData;
import android.content.ClipDescription;
import android.content.ClipboardManager;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.os.Build;
import android.os.Bundle;
import android.os.PersistableBundle;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class MainActivity extends AppCompatActivity implements ServerService.Listener {
    private static final String PREFS = "ninjatap";
    private static final int DEFAULT_PORT = 8787;

    private EditText portField;
    private EditText tokenField;
    private Spinner bindSpinner;
    private TextView statusView;
    private TextView detailView;
    private TextView serviceSummary;
    private Button actionButton;
    private Button refreshAddresses;
    private View settingsLocked;
    private View pairingPending;
    private View pairingValues;
    private TextView pairingUrl;
    private TextView pairingFingerprint;
    private Button copyConfig;
    private Button showToken;
    private Button copyToken;
    private Button rotateToken;
    private final List<String> addresses = new ArrayList<>();
    private String wlanAddress = "";
    private boolean tokenVisible;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        setContentView(R.layout.activity_main);
        View dashboard = findViewById(R.id.dashboard);
        ViewCompat.setOnApplyWindowInsetsListener(dashboard, (view, insets) -> {
            Insets safeArea = insets.getInsets(WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.displayCutout() | WindowInsetsCompat.Type.ime());
            view.setPadding(safeArea.left, safeArea.top, safeArea.right, safeArea.bottom);
            return insets;
        });
        ViewCompat.requestApplyInsets(dashboard);

        portField = findViewById(R.id.port);
        tokenField = findViewById(R.id.token);
        bindSpinner = findViewById(R.id.bind);
        statusView = findViewById(R.id.status);
        detailView = findViewById(R.id.detail);
        serviceSummary = findViewById(R.id.service_summary);
        actionButton = findViewById(R.id.action);
        refreshAddresses = findViewById(R.id.refresh_addresses);
        settingsLocked = findViewById(R.id.settings_locked);
        pairingPending = findViewById(R.id.pairing_pending);
        pairingValues = findViewById(R.id.pairing_values);
        pairingUrl = findViewById(R.id.pairing_url);
        pairingFingerprint = findViewById(R.id.pairing_fingerprint);
        copyConfig = findViewById(R.id.copy_config);
        showToken = findViewById(R.id.show_token);
        copyToken = findViewById(R.id.copy_token);
        rotateToken = findViewById(R.id.rotate_token);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && savedInstanceState == null
                && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                    this, new String[] {Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        loadFields();
        setTokenVisible(false);
        actionButton.setOnClickListener(this::onAction);
        refreshAddresses.setOnClickListener(view -> {
            reloadAddresses();
            Toast.makeText(this, R.string.addresses_refreshed, Toast.LENGTH_SHORT).show();
        });
        findViewById(R.id.copy_url).setOnClickListener(view ->
                copyText(R.string.label_url, pairingUrl.getText().toString(), false));
        findViewById(R.id.copy_fingerprint).setOnClickListener(view ->
                copyText(R.string.label_fingerprint, pairingFingerprint.getText().toString(), false));
        copyConfig.setOnClickListener(view -> copyPairingConfig());
        showToken.setOnClickListener(view -> setTokenVisible(!tokenVisible));
        copyToken.setOnClickListener(view ->
                copyText(R.string.label_token, tokenField.getText().toString().trim(), true));
        rotateToken.setOnClickListener(view -> confirmTokenRotation());
    }

    @Override
    protected void onStart() {
        super.onStart();
        reloadAddresses();
        ServerService.addListener(this);
        onState(ServerService.current());
    }

    @Override
    protected void onStop() {
        saveFields();
        setTokenVisible(false);
        ServerService.removeListener(this);
        super.onStop();
    }

    @Override
    public void onState(ServerService.State state) {
        runOnUiThread(() -> show(state));
    }

    private void onAction(View view) {
        ServerService.State state = ServerService.current();
        if (state.starting()) {
            return;
        }
        if (state.running()) {
            actionButton.setEnabled(false);
            ServerService.stop(this);
            return;
        }
        String token = tokenField.getText().toString().trim();
        int port;
        try {
            port = Integer.parseInt(portField.getText().toString().trim());
        } catch (NumberFormatException error) {
            showDetail(getString(R.string.invalid_port));
            return;
        }
        if (port < 1 || port > 65535) {
            showDetail(getString(R.string.invalid_port));
            return;
        }
        if (token.isEmpty() || token.chars().anyMatch(Character::isWhitespace)) {
            showDetail(getString(R.string.invalid_token));
            return;
        }
        String bind = (String) bindSpinner.getSelectedItem();
        if (bind == null || bind.isEmpty()) {
            showDetail(getString(R.string.missing_bind));
            return;
        }
        saveFields();
        String reachable = "0.0.0.0".equals(bind) && !wlanAddress.isEmpty() ? wlanAddress : bind;
        actionButton.setEnabled(false);
        ServerService.start(this, bind, port, token, reachable);
    }

    private void show(ServerService.State state) {
        if (state.running()) {
            showStatus(R.string.status_running, R.string.service_running,
                    R.color.accent, R.color.ready_background);
        } else if (state.starting()) {
            showStatus(R.string.status_starting, R.string.service_starting,
                    R.color.pending, R.color.pending_background);
        } else if (!state.error().isEmpty()) {
            showStatus(R.string.status_failed, R.string.service_failed,
                    R.color.danger, R.color.danger_background);
        } else {
            showStatus(R.string.status_stopped, R.string.service_idle,
                    R.color.muted, R.color.status_background);
        }
        showDetail(state.error());
        actionButton.setText(state.running() ? R.string.action_stop : R.string.action_start);
        actionButton.setEnabled(!state.starting());

        pairingUrl.setText(state.url());
        pairingFingerprint.setText(state.fingerprint());
        pairingPending.setVisibility(state.running() ? View.GONE : View.VISIBLE);
        pairingValues.setVisibility(state.running() ? View.VISIBLE : View.GONE);
        copyConfig.setEnabled(state.running());

        boolean editable = !state.running() && !state.starting();
        settingsLocked.setVisibility(state.running() ? View.VISIBLE : View.GONE);
        portField.setEnabled(editable);
        tokenField.setEnabled(editable);
        bindSpinner.setEnabled(editable);
        refreshAddresses.setEnabled(editable);
        rotateToken.setEnabled(editable);
    }

    private void showStatus(int status, int summary, int color, int background) {
        statusView.setText(status);
        statusView.setTextColor(ContextCompat.getColor(this, color));
        statusView.setBackgroundTintList(ColorStateList.valueOf(ContextCompat.getColor(this, background)));
        serviceSummary.setText(summary);
    }

    private void showDetail(String detail) {
        detailView.setText(detail);
        detailView.setVisibility(detail.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void setTokenVisible(boolean visible) {
        tokenVisible = visible;
        tokenField.setTransformationMethod(visible ? null : PasswordTransformationMethod.getInstance());
        tokenField.setTypeface(Typeface.MONOSPACE);
        showToken.setText(visible ? R.string.hide_token : R.string.show_token);
    }

    private void confirmTokenRotation() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.rotate_token)
                .setMessage(R.string.rotate_token_detail)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.rotate_token, (dialog, which) -> {
                    tokenField.setText(generateToken());
                    setTokenVisible(false);
                    saveFields();
                })
                .show();
    }

    private void copyPairingConfig() {
        ServerService.State state = ServerService.current();
        if (!state.running()) {
            return;
        }
        String config = "NINJATAP_URL=" + dotenvValue(state.url()) + "\n"
                + "NINJATAP_TLS_FINGERPRINT=" + dotenvValue(state.fingerprint()) + "\n"
                + "NINJATAP_SECRET=" + dotenvValue(tokenField.getText().toString().trim()) + "\n";
        copyText(R.string.copy_config, config, true);
    }

    private static String dotenvValue(String value) {
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'";
    }

    private void copyText(int label, String text, boolean sensitive) {
        if (text.isEmpty()) {
            return;
        }
        ClipboardManager clipboard = getSystemService(ClipboardManager.class);
        if (clipboard == null) {
            Toast.makeText(this, R.string.copy_failed, Toast.LENGTH_SHORT).show();
            return;
        }
        ClipData clip = ClipData.newPlainText(getString(label), text);
        if (sensitive && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            PersistableBundle extras = new PersistableBundle();
            extras.putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true);
            clip.getDescription().setExtras(extras);
        }
        clipboard.setPrimaryClip(clip);
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            Toast.makeText(this, R.string.copy_done, Toast.LENGTH_SHORT).show();
        }
    }

    private void loadFields() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        portField.setText(String.valueOf(prefs.getInt("port", DEFAULT_PORT)));
        String token = prefs.getString("token", "");
        tokenField.setText(token == null || token.isEmpty() ? generateToken() : token);
    }

    private static String generateToken() {
        byte[] bytes = new byte[16];
        new SecureRandom().nextBytes(bytes);
        StringBuilder token = new StringBuilder(32);
        for (byte value : bytes) {
            token.append(Character.forDigit((value & 0xff) >>> 4, 16));
            token.append(Character.forDigit(value & 0xf, 16));
        }
        return token.toString();
    }

    private void saveFields() {
        int port = DEFAULT_PORT;
        try {
            port = Integer.parseInt(portField.getText().toString().trim());
        } catch (NumberFormatException ignored) {
            // Keep the default when the field is mid-edit.
        }
        String bind = bindSpinner.getSelectedItem() == null
                ? "0.0.0.0"
                : bindSpinner.getSelectedItem().toString();
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putInt("port", port)
                .putString("token", tokenField.getText().toString().trim())
                .putString("bind", bind)
                .apply();
    }

    private void reloadAddresses() {
        String selected = bindSpinner.getSelectedItem() instanceof String current
                ? current : getSharedPreferences(PREFS, MODE_PRIVATE).getString("bind", "");
        addresses.clear();
        wlanAddress = "";
        addresses.add("0.0.0.0");
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) {
                    continue;
                }
                for (Inet4Address address : ipv4(nif)) {
                    String host = address.getHostAddress();
                    if (host == null || addresses.contains(host)) {
                        continue;
                    }
                    addresses.add(host);
                    if (wlanAddress.isEmpty() && nif.getName().startsWith("wlan")) {
                        wlanAddress = host;
                    }
                }
            }
        } catch (Exception ignored) {
            // The spinner still offers 0.0.0.0 when the interfaces cannot be listed.
        }
        addLinkAddresses();
        ArrayAdapter<String> adapter = new ArrayAdapter<>(
                this, android.R.layout.simple_spinner_item, addresses);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        bindSpinner.setAdapter(adapter);
        int index = addresses.indexOf(selected);
        if (index < 0) {
            index = wlanAddress.isEmpty() ? 0 : addresses.indexOf(wlanAddress);
        }
        bindSpinner.setSelection(Math.max(index, 0));
    }

    private void addLinkAddresses() {
        ConnectivityManager manager = getSystemService(ConnectivityManager.class);
        if (manager == null) {
            return;
        }
        for (Network network : manager.getAllNetworks()) {
            LinkProperties properties = manager.getLinkProperties(network);
            if (properties == null) {
                continue;
            }
            String name = properties.getInterfaceName();
            boolean wifi = name != null && name.startsWith("wlan");
            for (LinkAddress link : properties.getLinkAddresses()) {
                if (!(link.getAddress() instanceof Inet4Address inet4) || inet4.isLoopbackAddress()) {
                    continue;
                }
                String host = inet4.getHostAddress();
                if (host == null || addresses.contains(host)) {
                    if (wifi && host != null && wlanAddress.isEmpty()) {
                        wlanAddress = host;
                    }
                    continue;
                }
                addresses.add(host);
                if (wifi && wlanAddress.isEmpty()) {
                    wlanAddress = host;
                }
            }
        }
    }

    private static List<Inet4Address> ipv4(NetworkInterface nif) {
        List<Inet4Address> found = new ArrayList<>();
        for (java.net.InetAddress address : Collections.list(nif.getInetAddresses())) {
            if (address instanceof Inet4Address inet4 && !inet4.isLoopbackAddress()) {
                found.add(inet4);
            }
        }
        return found;
    }
}
