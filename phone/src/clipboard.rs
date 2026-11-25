//! Read and write the phone clipboard by running the app helper as shell.
//!
//! The player itself is root. Root does not own `com.android.shell`, and
//! Android rejects a clipboard read from a package the caller does not own.
//! Shell holds `READ_CLIPBOARD_IN_BACKGROUND`, so the helper runs as uid 2000.

use std::process::{Command, Stdio};

const PACKAGE: &str = "com.ninjatap.player";
const CLASS: &str = "com.ninjatap.player.ClipboardCli";
const APK_COPY: &str = "/data/local/tmp/ninjatap-clip.apk";
const TEXT_FILE: &str = "/data/local/tmp/ninjatap.clip";
const SHELL_UID: &str = "2000";

#[derive(Debug)]
pub struct ClipError(pub String);

impl std::fmt::Display for ClipError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(formatter)
    }
}

pub fn read() -> Result<String, ClipError> {
    let classpath = classpath()?;
    let output = run_shell(&format!(
        "export CLASSPATH={apk}; exec /system/bin/app_process /system/bin {CLASS} get",
        apk = quote(&classpath),
    ))?;
    Ok(output)
}

pub fn write(text: &str) -> Result<(), ClipError> {
    let classpath = classpath()?;
    std::fs::write(TEXT_FILE, text.as_bytes()).map_err(|error| ClipError(error.to_string()))?;
    chown_shell(TEXT_FILE)?;
    run_shell(&format!(
        "export CLASSPATH={apk}; exec /system/bin/app_process /system/bin {CLASS} set {file}",
        apk = quote(&classpath),
        file = quote(TEXT_FILE),
    ))?;
    let _ = std::fs::remove_file(TEXT_FILE);
    Ok(())
}

fn classpath() -> Result<String, ClipError> {
    let listed = Command::new("/system/bin/pm")
        .args(["path", PACKAGE])
        .output()
        .map_err(|error| ClipError(error.to_string()))?;
    if !listed.status.success() {
        return Err(ClipError(stderr_of(&listed)));
    }
    let listed_text = String::from_utf8_lossy(&listed.stdout);
    let apk = apk_from_pm(&listed_text)
        .ok_or_else(|| ClipError("player apk not installed".into()))?;
    std::fs::copy(apk, APK_COPY).map_err(|error| ClipError(error.to_string()))?;
    chmod(APK_COPY, "644")?;
    Ok(APK_COPY.into())
}

fn chown_shell(path: &str) -> Result<(), ClipError> {
    let status = Command::new("/system/bin/chown")
        .args(["2000:2000", path])
        .status()
        .map_err(|error| ClipError(error.to_string()))?;
    if !status.success() {
        return Err(ClipError(format!("chown {path} failed")));
    }
    chmod(path, "600")
}

fn chmod(path: &str, mode: &str) -> Result<(), ClipError> {
    let status = Command::new("/system/bin/chmod")
        .args([mode, path])
        .status()
        .map_err(|error| ClipError(error.to_string()))?;
    if status.success() {
        Ok(())
    } else {
        Err(ClipError(format!("chmod {path} failed")))
    }
}

fn run_shell(script: &str) -> Result<String, ClipError> {
    let output = Command::new("/system/bin/su")
        .args([SHELL_UID, "-c", script])
        .stdin(Stdio::null())
        .output()
        .map_err(|error| ClipError(error.to_string()))?;
    if output.status.success() {
        return Ok(String::from_utf8_lossy(&output.stdout).into_owned());
    }
    let detail = stderr_of(&output);
    Err(ClipError(if detail.is_empty() {
        format!("clipboard helper exited {}", output.status)
    } else {
        detail
    }))
}

fn stderr_of(output: &std::process::Output) -> String {
    let mut detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if detail.len() > 500 {
        detail.truncate(500);
    }
    detail
}

fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn apk_from_pm(output: &str) -> Option<&str> {
    output.lines().find_map(|line| {
        let path = line.trim().strip_prefix("package:")?;
        if path.ends_with("/base.apk") {
            Some(path)
        } else {
            None
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_base_apk_path() {
        let output = "package:/data/app/~~ab/com.ninjatap.player-cd==/base.apk\npackage:/data/app/~~ab/com.ninjatap.player-cd==/split.apk\n";
        assert_eq!(
            apk_from_pm(output),
            Some("/data/app/~~ab/com.ninjatap.player-cd==/base.apk")
        );
        assert_eq!(apk_from_pm("not a path\n"), None);
    }

    #[test]
    fn quotes_a_path_for_the_shell() {
        assert_eq!(quote("/data/local/tmp/a.apk"), "'/data/local/tmp/a.apk'");
        assert_eq!(quote("a'b"), "'a'\\''b'");
    }
}
