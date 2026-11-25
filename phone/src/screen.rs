//! Screen-off and rotation gate. Reads `dumpsys display`.

use std::{io, process::Command};

use crate::protocol::Status;

#[derive(Debug, PartialEq, Eq)]
pub enum ScreenError {
    Unreadable,
    Blocked(Status),
}

#[cfg(target_os = "android")]
pub fn control(command: u8) -> io::Result<String> {
    use std::io::{Read, Write};
    use std::os::android::net::SocketAddrExt;
    use std::os::unix::net::{SocketAddr, UnixStream};
    use std::process::Stdio;
    use std::time::Duration;

    let name = std::env::var_os("NINJATAP_SCREEN_SOCKET").ok_or(io::ErrorKind::NotConnected)?;
    let address = SocketAddr::from_abstract_name(name.as_encoded_bytes())?;
    let mut stream = UnixStream::connect_addr(&address).map_err(|_| io::ErrorKind::NotConnected)?;
    // MagicOS can freeze the Java app even while its foreground service is running.
    // Wake from the native player so the app can receive the unlock request.
    if command == b'U'
        && !Command::new("/system/bin/timeout")
            .args(["3", "/system/bin/input", "keyevent", "KEYCODE_WAKEUP"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|status| status.success())
    {
        return Ok("screen_wake_failed".into());
    }

    // The app acknowledges the connection before we send an action. An expired
    // connection waiting on a frozen app therefore contains no pending command.
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    let mut ready = [0];
    stream.read_exact(&mut ready)?;
    if ready != [b'R'] {
        return Err(io::ErrorKind::InvalidData.into());
    }
    stream.set_write_timeout(Some(Duration::from_secs(1)))?;
    stream.set_read_timeout(Some(Duration::from_secs(16)))?;
    stream.write_all(&[command])?;
    let mut status = String::new();
    stream.take(64).read_to_string(&mut status)?;
    Ok(status.trim_end().to_owned())
}

#[cfg(not(target_os = "android"))]
pub fn control(_: u8) -> io::Result<String> {
    Err(io::ErrorKind::NotConnected.into())
}

pub fn ensure_ready() -> Result<(), ScreenError> {
    let output = Command::new("/system/bin/dumpsys")
        .arg("display")
        .output()
        .map_err(|_| ScreenError::Unreadable)?;
    if !output.status.success() {
        return Err(ScreenError::Unreadable);
    }
    let text = String::from_utf8_lossy(&output.stdout);
    decide(&text).map_err(ScreenError::Blocked)
}

pub fn decide(dump: &str) -> Result<(), Status> {
    let mut state = None;
    let mut orientation = None;
    for line in dump.lines() {
        let line = line.trim();
        if let Some(value) = line.strip_prefix("mScreenState=") {
            state = Some(value.trim());
        } else if let Some(value) = line.strip_prefix("mCurrentOrientation=") {
            orientation = Some(value.trim());
        }
    }
    if state != Some("ON") {
        return Err(Status::ScreenOff);
    }
    if orientation != Some("0") {
        return Err(Status::Rotation);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn portrait_and_on_passes() {
        let dump = "noise state ON rotation 0\n    mCurrentOrientation=0\n  mScreenState=ON\n";
        assert_eq!(decide(dump), Ok(()));
    }

    #[test]
    fn off_screen_is_rejected() {
        let dump = "mCurrentOrientation=0\nmScreenState=OFF\n";
        assert_eq!(decide(dump), Err(Status::ScreenOff));
    }

    #[test]
    fn rotated_screen_is_rejected() {
        let dump = "mCurrentOrientation=1\nmScreenState=ON\n";
        assert_eq!(decide(dump), Err(Status::Rotation));
    }
}
