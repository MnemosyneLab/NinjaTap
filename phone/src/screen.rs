//! Screen-off and rotation gate. Reads `dumpsys display`.

use std::process::Command;

use crate::protocol::Status;

#[derive(Debug, PartialEq, Eq)]
pub enum ScreenError {
    Unreadable,
    Blocked(Status),
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
