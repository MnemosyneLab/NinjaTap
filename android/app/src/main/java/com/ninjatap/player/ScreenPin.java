package com.ninjatap.player;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Arrays;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class ScreenPin {
    static final int LENGTH = 6;
    private static final String ALIAS = "ninjatap-screen-pin";
    private static final String PIN = "pin";
    private static final String ATTEMPTED = "attempted";
    private static final int IV_LENGTH = 12;
    private final SharedPreferences prefs;

    ScreenPin(Context context) {
        prefs = context.getSharedPreferences("screen_control", Context.MODE_PRIVATE);
    }

    String saved() {
        return prefs.getString(PIN, null);
    }

    boolean needsReset() {
        return prefs.getBoolean(ATTEMPTED, false);
    }

    void addStatusListener(SharedPreferences.OnSharedPreferenceChangeListener listener) {
        prefs.registerOnSharedPreferenceChangeListener(listener);
    }

    void removeStatusListener(SharedPreferences.OnSharedPreferenceChangeListener listener) {
        prefs.unregisterOnSharedPreferenceChangeListener(listener);
    }

    void save(byte[] digits) throws GeneralSecurityException, IOException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(true));
        byte[] ciphertext = cipher.doFinal(digits);
        byte[] sealed = Arrays.copyOf(cipher.getIV(), IV_LENGTH + ciphertext.length);
        System.arraycopy(ciphertext, 0, sealed, IV_LENGTH, ciphertext.length);
        synchronized (ScreenPin.class) {
            persist(prefs.edit().putString(PIN, Base64.encodeToString(sealed, Base64.NO_WRAP))
                    .remove(ATTEMPTED));
        }
    }

    void clear() throws IOException {
        synchronized (ScreenPin.class) {
            persist(prefs.edit().clear());
        }
    }

    byte[] decrypt(String saved) throws GeneralSecurityException, IOException {
        byte[] sealed = Base64.decode(saved, Base64.NO_WRAP);
        if (sealed.length != IV_LENGTH + LENGTH + 16) {
            throw new GeneralSecurityException("Invalid encrypted PIN");
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, sealed, 0, IV_LENGTH));
        return cipher.doFinal(sealed, IV_LENGTH, sealed.length - IV_LENGTH);
    }

    boolean beginAttempt(String saved) throws IOException {
        synchronized (ScreenPin.class) {
            if (!saved.equals(saved()) || needsReset()) {
                return false;
            }
            persist(prefs.edit().putBoolean(ATTEMPTED, true));
            return true;
        }
    }

    void confirmAttempt(String saved) throws IOException {
        synchronized (ScreenPin.class) {
            if (saved.equals(saved())) {
                persist(prefs.edit().remove(ATTEMPTED));
            }
        }
    }

    void resetAttempt() throws IOException {
        synchronized (ScreenPin.class) {
            persist(prefs.edit().remove(ATTEMPTED));
        }
    }

    private static SecretKey key(boolean create) throws GeneralSecurityException, IOException {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        SecretKey key = (SecretKey) store.getKey(ALIAS, null);
        if (key != null) {
            return key;
        }
        if (!create) {
            throw new GeneralSecurityException("Screen PIN key is missing");
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        // The app must be able to use this key while the screen is locked.
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build());
        return generator.generateKey();
    }

    private static void persist(SharedPreferences.Editor edit) throws IOException {
        if (!edit.commit()) {
            throw new IOException("Could not save screen control settings");
        }
    }
}
