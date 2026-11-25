package com.ninjatap.player;

import android.Manifest;
import android.app.KeyguardManager;
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
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;

import java.io.IOException;
import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

public final class MainActivity extends AppCompatActivity implements ServerService.Listener {
    private static final String PREFS = "ninjatap";
    private static final String SELECTED_PAGE = "selected_page";
    private static final int DEFAULT_PORT = 8787;
    private static final int CONTROL = 0;
    private static final int PAIRING = 1;
    private static final int SETTINGS = 2;
    private static final int[] PAGE_IDS = {R.id.page_control, R.id.page_pairing, R.id.page_settings};
    private static final int[] NAV_IDS = {R.id.nav_control, R.id.nav_pairing, R.id.nav_settings};

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
    private Button configurePin;
    private TextView screenControlStatus;
    private TextView controlPinStatus;
    private ScreenPin screenPin;
    private OnBackPressedCallback backToControl;
    private int selectedPage;
    private final SharedPreferences.OnSharedPreferenceChangeListener pinStatusChanged =
            (preferences, key) -> updateScreenControl();
    private final List<String> addresses = new ArrayList<>();
    private String wlanAddress = "";
    private boolean tokenVisible;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        setContentView(R.layout.activity_main);
        View dashboard = findViewById(R.id.dashboard);
        View appBar = findViewById(R.id.app_bar);
        View bottomNavigation = findViewById(R.id.bottom_navigation);
        int navigationPadding = bottomNavigation.getPaddingStart();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        ViewCompat.setOnApplyWindowInsetsListener(dashboard, (view, insets) -> {
            Insets safeArea = insets.getInsets(WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.displayCutout());
            Insets keyboard = insets.getInsets(WindowInsetsCompat.Type.ime());
            view.setPadding(safeArea.left, 0, safeArea.right, keyboard.bottom);
            appBar.setPadding(0, safeArea.top, 0, 0);
            bottomNavigation.setPaddingRelative(navigationPadding, 0, navigationPadding, safeArea.bottom);
            bottomNavigation.setVisibility(keyboard.bottom > safeArea.bottom ? View.GONE : View.VISIBLE);
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
        configurePin = findViewById(R.id.configure_screen_pin);
        screenControlStatus = findViewById(R.id.screen_control_status);
        controlPinStatus = findViewById(R.id.control_pin_status);
        screenPin = new ScreenPin(this);
        configurePin.setOnClickListener(view -> editScreenPin());

        backToControl = new OnBackPressedCallback(false) {
            @Override
            public void handleOnBackPressed() {
                selectPage(CONTROL);
            }
        };
        getOnBackPressedDispatcher().addCallback(this, backToControl);
        for (int index = 0; index < NAV_IDS.length; index++) {
            int page = index;
            findViewById(NAV_IDS[index]).setOnClickListener(view -> selectPage(page));
        }
        findViewById(R.id.open_pairing).setOnClickListener(view -> selectPage(PAIRING));
        findViewById(R.id.back_to_control).setOnClickListener(view -> selectPage(CONTROL));
        findViewById(R.id.open_pin_settings).setOnClickListener(view -> selectPage(SETTINGS));
        selectPage(savedInstanceState == null ? CONTROL : savedInstanceState.getInt(SELECTED_PAGE, CONTROL));

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

    private void selectPage(int page) {
        selectedPage = page;
        for (int index = 0; index < PAGE_IDS.length; index++) {
            boolean selected = page == index;
            findViewById(PAGE_IDS[index]).setVisibility(selected ? View.VISIBLE : View.GONE);
            findViewById(NAV_IDS[index]).setSelected(selected);
        }
        backToControl.setEnabled(page != CONTROL);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        outState.putInt(SELECTED_PAGE, selectedPage);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onStart() {
        super.onStart();
        reloadAddresses();
        ServerService.addListener(this);
        screenPin.addStatusListener(pinStatusChanged);
        onState(ServerService.current());
    }

    @Override
    protected void onStop() {
        saveFields();
        setTokenVisible(false);
        ServerService.removeListener(this);
        screenPin.removeStatusListener(pinStatusChanged);
        super.onStop();
    }

    @Override
    public void onState(ServerService.State state) {
        runOnUiThread(() -> show(state));
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateScreenControl();
    }

    private void updateScreenControl() {
        int status = screenPin.saved() == null ? R.string.screen_pin_missing
                : screenPin.needsReset() ? R.string.screen_pin_reset : R.string.screen_pin_saved;
        screenControlStatus.setText(status);
        controlPinStatus.setText(status);
    }

    private void editScreenPin() {
        EditText field = new EditText(this);
        field.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        field.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING);
        field.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        field.setSaveEnabled(false);
        field.setHint(R.string.screen_pin_hint);
        field.setBackgroundResource(R.drawable.field_background);
        field.setPaddingRelative(dp(14), dp(10), dp(14), dp(10));
        field.setMinHeight(dp(52));
        FrameLayout input = new FrameLayout(this);
        input.setPaddingRelative(dp(24), dp(12), dp(24), dp(4));
        input.addView(field, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT));
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(R.string.configure_screen_pin)
                .setMessage(R.string.screen_pin_description)
                .setView(input)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.screen_pin_save, null);
        if (screenPin.saved() != null) {
            builder.setNeutralButton(R.string.screen_pin_clear, (dialog, which) -> {
                try {
                    screenPin.clear();
                    updateScreenControl();
                } catch (IOException error) {
                    Toast.makeText(this, R.string.screen_pin_storage_error, Toast.LENGTH_SHORT).show();
                }
            });
        }
        AlertDialog dialog = builder.create();
        dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
        field.requestFocus();
        dialog.setOnDismissListener(ignored -> field.getText().clear());
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(view -> saveScreenPin(field, dialog)));
        dialog.show();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void saveScreenPin(EditText field, AlertDialog dialog) {
        var entered = field.getText();
        if (entered.length() != ScreenPin.LENGTH) {
            field.setError(getString(R.string.screen_pin_hint));
            return;
        }
        byte[] digits = new byte[ScreenPin.LENGTH];
        try {
            for (int i = 0; i < digits.length; i++) {
                char digit = entered.charAt(i);
                if (digit < '0' || digit > '9') {
                    field.setError(getString(R.string.screen_pin_hint));
                    return;
                }
                digits[i] = (byte) digit;
            }
            screenPin.save(digits);
            dialog.dismiss();
            updateScreenControl();
        } catch (IOException | GeneralSecurityException error) {
            field.setError(getString(R.string.screen_pin_storage_error));
        } finally {
            Arrays.fill(digits, (byte) 0);
        }
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
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        if (screenPin.needsReset() && !keyguard.isDeviceLocked() && !keyguard.isKeyguardLocked()) {
            try {
                screenPin.resetAttempt();
            } catch (IOException error) {
                Toast.makeText(this, R.string.screen_pin_storage_error, Toast.LENGTH_SHORT).show();
            }
        }
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
        actionButton.setBackgroundResource(state.running() ? R.drawable.stop_background : R.drawable.action_background);
        actionButton.setTextColor(ContextCompat.getColorStateList(this,
                state.running() ? R.color.control_text : R.color.primary_button_text));
        actionButton.setEnabled(!state.starting());

        pairingUrl.setText(state.url());
        pairingFingerprint.setText(state.fingerprint());
        pairingPending.setVisibility(state.running() ? View.GONE : View.VISIBLE);
        pairingValues.setVisibility(state.running() ? View.VISIBLE : View.GONE);
        copyConfig.setEnabled(state.running());

        boolean editable = !state.running() && !state.starting();
        settingsLocked.setVisibility(editable ? View.GONE : View.VISIBLE);
        portField.setEnabled(editable);
        tokenField.setEnabled(editable);
        bindSpinner.setEnabled(editable);
        refreshAddresses.setEnabled(editable);
        rotateToken.setEnabled(editable);
        configurePin.setEnabled(editable);
        updateScreenControl();
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
