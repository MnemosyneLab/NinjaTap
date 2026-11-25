//! JSON body for `POST /inject`, and the status values the player returns.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct InjectRequest {
    #[serde(default)]
    pub rotation: u8,
    pub sequence: Vec<Step>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "action", rename_all = "lowercase")]
pub enum Step {
    Down {
        x: i32,
        y: i32,
        id: i32,
        pressure: i32,
        major: i32,
        minor: i32,
        orientation: i32,
    },
    Move {
        x: i32,
        y: i32,
        id: i32,
        pressure: i32,
        major: i32,
        minor: i32,
        orientation: i32,
    },
    Up { id: i32 },
    Sleep { ms: u64 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Ok,
    ScreenOff,
    Rotation,
    RotationChanged,
    NoDevice,
    Closed,
    Unauthorized,
    /// A real finger is already on the screen.
    Contact,
}

#[derive(Debug, Serialize)]
pub struct InjectResponse {
    pub status: Status,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_tap_and_serializes_status() {
        let raw = r#"{
            "sequence": [
                {"action": "down", "x": 632, "y": 1500, "id": 0, "pressure": 248, "major": 171, "minor": 154, "orientation": -22},
                {"action": "sleep", "ms": 17},
                {"action": "move", "x": 632, "y": 1500, "id": 0, "pressure": 410, "major": 190, "minor": 168, "orientation": -18},
                {"action": "up", "id": 0}
            ]
        }"#;
        let request: InjectRequest = serde_json::from_str(raw).unwrap();
        assert_eq!(request.rotation, 0);
        assert_eq!(
            request.sequence,
            vec![
                Step::Down {
                    x: 632,
                    y: 1500,
                    id: 0,
                    pressure: 248,
                    major: 171,
                    minor: 154,
                    orientation: -22,
                },
                Step::Sleep { ms: 17 },
                Step::Move {
                    x: 632,
                    y: 1500,
                    id: 0,
                    pressure: 410,
                    major: 190,
                    minor: 168,
                    orientation: -18,
                },
                Step::Up { id: 0 },
            ]
        );
        let names = [
            Status::Ok,
            Status::ScreenOff,
            Status::Rotation,
            Status::RotationChanged,
            Status::NoDevice,
            Status::Closed,
            Status::Unauthorized,
            Status::Contact,
        ];
        let body: Vec<_> = names
            .iter()
            .map(|status| serde_json::to_string(&InjectResponse { status: *status }).unwrap())
            .collect();
        assert_eq!(
            body,
            vec![
                r#"{"status":"ok"}"#,
                r#"{"status":"screen_off"}"#,
                r#"{"status":"rotation"}"#,
                r#"{"status":"rotation_changed"}"#,
                r#"{"status":"no_device"}"#,
                r#"{"status":"closed"}"#,
                r#"{"status":"unauthorized"}"#,
                r#"{"status":"contact"}"#,
            ]
        );
    }
}
