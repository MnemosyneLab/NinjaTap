//! Runs `/system/bin/screencap` for the main display and returns the PNG bytes.

use std::process::Command;

use crate::device;

#[derive(Debug, PartialEq, Eq)]
pub enum CaptureError {
    Failed,
}

pub fn command() -> Vec<String> {
    vec![
        "/system/bin/screencap".to_string(),
        "-p".to_string(),
        "-d".to_string(),
        device::DISPLAY_ID.to_string(),
    ]
}

pub fn png() -> Result<Vec<u8>, CaptureError> {
    let mut args = command();
    let program = args.remove(0);
    let output = Command::new(program)
        .args(&args)
        .output()
        .map_err(|_| CaptureError::Failed)?;
    if !output.status.success() || !output.stdout.starts_with(b"\x89PNG") {
        eprintln!(
            "screencap failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        return Err(CaptureError::Failed);
    }
    Ok(output.stdout)
}

pub fn size(png: &[u8]) -> Option<(i32, i32)> {
    if png.get(..16)? != b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" {
        return None;
    }
    let width = i32::from_be_bytes(png.get(16..20)?.try_into().ok()?);
    let height = i32::from_be_bytes(png.get(20..24)?.try_into().ok()?);
    Some((width, height))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn screencap_targets_the_main_display() {
        assert_eq!(
            command(),
            vec!["/system/bin/screencap", "-p", "-d", "4630946363286114434",]
        );
    }
}
