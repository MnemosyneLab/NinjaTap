//! Primary display state and conversion from screen pixels to native touch pixels.

use std::{io, process::Command};

use crate::device::{HEIGHT, WIDTH};
use crate::protocol::Status;

#[derive(Debug, PartialEq, Eq)]
pub enum ScreenError {
    Unreadable,
    Blocked(Status),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rotation {
    Upright = 0,
    QuarterTurn = 1,
    HalfTurn = 2,
    ThreeQuarterTurn = 3,
}

impl Rotation {
    pub fn from_android(value: u8) -> Option<Self> {
        match value {
            0 => Some(Self::Upright),
            1 => Some(Self::QuarterTurn),
            2 => Some(Self::HalfTurn),
            3 => Some(Self::ThreeQuarterTurn),
            _ => None,
        }
    }

    pub fn size(self) -> (i32, i32) {
        match self {
            Self::Upright | Self::HalfTurn => (WIDTH, HEIGHT),
            Self::QuarterTurn | Self::ThreeQuarterTurn => (HEIGHT, WIDTH),
        }
    }

    pub fn native_point(self, x: i32, y: i32) -> Option<(i32, i32)> {
        let (width, height) = self.size();
        if !(0..width).contains(&x) || !(0..height).contains(&y) {
            return None;
        }
        Some(match self {
            Self::Upright => (x, y),
            Self::QuarterTurn => (WIDTH - 1 - y, x),
            Self::HalfTurn => (WIDTH - 1 - x, HEIGHT - 1 - y),
            Self::ThreeQuarterTurn => (y, HEIGHT - 1 - x),
        })
    }
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

pub fn ensure_ready() -> Result<Rotation, ScreenError> {
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

fn decide(dump: &str) -> Result<Rotation, Status> {
    let mut state = None;
    let mut base = None;
    let mut overridden = None;
    let mut primary_power_controller = false;
    for line in dump.lines() {
        let line = line.trim();
        if line == "Display Power Controller:" {
            primary_power_controller = false;
        } else if let Some(id) = line.strip_prefix("mDisplayId=") {
            primary_power_controller = id == "0";
        } else if primary_power_controller {
            if let Some(value) = line.strip_prefix("mScreenState=") {
                state = Some(value);
            }
        }
        if line.contains(", displayId 0,") {
            if line.starts_with("mBaseDisplayInfo=") {
                base = display_rotation(line);
            } else if line.starts_with("mOverrideDisplayInfo=") {
                overridden = Some(display_rotation(line));
            }
        }
    }
    if state != Some("ON") {
        return Err(Status::ScreenOff);
    }
    overridden.unwrap_or(base).ok_or(Status::Rotation)
}

fn display_rotation(line: &str) -> Option<Rotation> {
    let value = line
        .split(", ")
        .find_map(|field| field.strip_prefix("rotation "))?;
    Rotation::from_android(value.parse().ok()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dump(rotation: u8, state: &str) -> String {
        format!(
            "mBaseDisplayInfo=DisplayInfo{{\"Built-in screen\", displayId 0, rotation 0, type INTERNAL}}\n\
            mOverrideDisplayInfo=DisplayInfo{{\"Built-in screen\", displayId 0, rotation {rotation}, type INTERNAL}}\n\
            mOverrideDisplayInfo=DisplayInfo{{\"Virtual\", displayId 5, rotation 0, type VIRTUAL}}\n\
            Display Power Controller:\nmDisplayId=0\nmScreenState={state}\n\
            Display Power Controller:\nmDisplayId=5\nmScreenState=OFF"
        )
    }

    #[test]
    fn uses_logical_rotation_and_power_state_of_the_primary_display() {
        for value in 0..=3 {
            assert_eq!(
                decide(&dump(value, "ON")),
                Ok(Rotation::from_android(value).unwrap())
            );
        }
    }

    #[test]
    fn off_screen_is_rejected() {
        assert_eq!(decide(&dump(1, "OFF")), Err(Status::ScreenOff));
    }

    #[test]
    fn maps_rotated_frame_corners_to_the_native_touch_axes() {
        for rotation in [
            Rotation::Upright,
            Rotation::QuarterTurn,
            Rotation::HalfTurn,
            Rotation::ThreeQuarterTurn,
        ] {
            let (w, h) = rotation.size();
            let (n0, n1) = match rotation {
                Rotation::Upright => ((0, 0), (WIDTH - 1, HEIGHT - 1)),
                Rotation::QuarterTurn => ((WIDTH - 1, 0), (0, HEIGHT - 1)),
                Rotation::HalfTurn => ((WIDTH - 1, HEIGHT - 1), (0, 0)),
                Rotation::ThreeQuarterTurn => ((0, HEIGHT - 1), (WIDTH - 1, 0)),
            };
            assert_eq!(rotation.native_point(0, 0), Some(n0));
            assert_eq!(rotation.native_point(w - 1, h - 1), Some(n1));
            assert_eq!(rotation.native_point(w, h - 1), None);
        }
    }
}
