//! Turns a sequence into frames and writes them to the touch node.
//!
//! `down` and `move` steps that sit before the next `sleep` or `up` belong to one frame.
//! `BTN_TOUCH` goes down with the first contact and up only when the last contact lifts.

use std::thread;
use std::time::{Duration, Instant};

use crate::input::{lift_frame, position, Contact, Frame, FrameBuilder, Touch};
use crate::protocol::{Status, Step};

const MAX_SLEEP_MS: u64 = 15_000;
const MAX_RUNTIME: Duration = Duration::from_secs(18);

#[derive(Debug, PartialEq, Eq)]
pub enum PlayError {
    /// The screen or the device refused the sequence.
    Blocked(Status),
    /// A pixel does not fit this phone's axis.
    Axis(crate::input::AxisOutOfRange),
    TooLong,
    TimedOut,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Beat {
    Frame { contacts: Vec<Contact> },
    Sleep(u64),
    Up(i32),
}

pub fn beats(steps: &[Step]) -> Vec<Beat> {
    let mut beats = Vec::new();
    let mut contacts = Vec::new();
    for step in steps {
        match step {
            Step::Down {
                x,
                y,
                id,
                pressure,
                major,
                minor,
                orientation,
            } => {
                contacts.push(Contact {
                    id: *id,
                    x: *x,
                    y: *y,
                    down: true,
                    pressure: *pressure,
                    major: *major,
                    minor: *minor,
                    orientation: *orientation,
                });
            }
            Step::Move {
                x,
                y,
                id,
                pressure,
                major,
                minor,
                orientation,
            } => {
                contacts.push(Contact {
                    id: *id,
                    x: *x,
                    y: *y,
                    down: false,
                    pressure: *pressure,
                    major: *major,
                    minor: *minor,
                    orientation: *orientation,
                });
            }
            Step::Sleep { ms } => {
                flush(&mut beats, &mut contacts);
                beats.push(Beat::Sleep(*ms));
            }
            Step::Up { id } => {
                flush(&mut beats, &mut contacts);
                beats.push(Beat::Up(*id));
            }
        }
    }
    flush(&mut beats, &mut contacts);
    beats
}

fn flush(beats: &mut Vec<Beat>, contacts: &mut Vec<Contact>) {
    if contacts.is_empty() {
        return;
    }
    beats.push(Beat::Frame {
        contacts: std::mem::take(contacts),
    });
}

struct Finger {
    id: i32,
    x: i32,
    y: i32,
    pressure: i32,
    major: i32,
    minor: i32,
    orientation: i32,
}

pub fn play(steps: &[Step]) -> Result<(), PlayError> {
    let mut touch = Touch::open().map_err(|_| PlayError::Blocked(Status::NoDevice))?;
    if touch.finger_present() {
        return Err(PlayError::Blocked(Status::Contact));
    }
    play_on(steps, &mut touch)
}

fn play_on(steps: &[Step], out: &mut impl WriteFrame) -> Result<(), PlayError> {
    validate(steps)?;
    let deadline = Instant::now() + MAX_RUNTIME;
    let mut fingers = Vec::new();
    for beat in beats(steps) {
        if Instant::now() >= deadline {
            release(out, &mut fingers)?;
            return Err(PlayError::TimedOut);
        }
        match beat {
            Beat::Frame { contacts } => {
                let mut builder = FrameBuilder::new();
                for contact in &contacts {
                    if let Err(error) = builder.contact(contact.clone()) {
                        release(out, &mut fingers)?;
                        return Err(PlayError::Axis(error));
                    }
                }
                let starting = fingers.is_empty();
                for contact in contacts {
                    remember(&mut fingers, &contact);
                }
                if !fingers.is_empty() {
                    out.note_held(true);
                }
                out.write_frame(&builder.finish(starting && !fingers.is_empty()))?;
            }
            Beat::Sleep(ms) => {
                thread::sleep(
                    Duration::from_millis(ms)
                        .min(deadline.saturating_duration_since(Instant::now())),
                );
            }
            Beat::Up(id) => {
                let had_fingers = !fingers.is_empty();
                fingers.retain(|finger| finger.id != id);
                if fingers.is_empty() {
                    if had_fingers {
                        out.write_frame(&lift_frame())?;
                        out.note_held(false);
                    }
                } else {
                    let mut builder = FrameBuilder::new();
                    for finger in &fingers {
                        builder
                            .contact(Contact {
                                id: finger.id,
                                x: finger.x,
                                y: finger.y,
                                down: false,
                                pressure: finger.pressure,
                                major: finger.major,
                                minor: finger.minor,
                                orientation: finger.orientation,
                            })
                            .map_err(PlayError::Axis)?;
                    }
                    out.note_held(true);
                    out.write_frame(&builder.finish(false))?;
                }
            }
        }
    }
    if !fingers.is_empty() {
        release(out, &mut fingers)?;
    }
    if Instant::now() >= deadline {
        Err(PlayError::TimedOut)
    } else {
        Ok(())
    }
}

fn validate(steps: &[Step]) -> Result<(), PlayError> {
    let mut sleep_ms = 0u64;
    for step in steps {
        match *step {
            Step::Down { x, y, .. } | Step::Move { x, y, .. } => {
                position(x, y).map_err(PlayError::Axis)?;
            }
            Step::Sleep { ms } => {
                sleep_ms = sleep_ms.saturating_add(ms);
                if sleep_ms > MAX_SLEEP_MS {
                    return Err(PlayError::TooLong);
                }
            }
            Step::Up { .. } => {}
        }
    }
    Ok(())
}

fn remember(fingers: &mut Vec<Finger>, contact: &Contact) {
    if let Some(found) = fingers.iter_mut().find(|finger| finger.id == contact.id) {
        found.x = contact.x;
        found.y = contact.y;
        found.pressure = contact.pressure;
        found.major = contact.major;
        found.minor = contact.minor;
        found.orientation = contact.orientation;
        return;
    }
    if contact.down {
        fingers.push(Finger {
            id: contact.id,
            x: contact.x,
            y: contact.y,
            pressure: contact.pressure,
            major: contact.major,
            minor: contact.minor,
            orientation: contact.orientation,
        });
    }
}

fn release(out: &mut impl WriteFrame, fingers: &mut Vec<Finger>) -> Result<(), PlayError> {
    let down = !fingers.is_empty();
    fingers.clear();
    if down {
        out.write_frame(&lift_frame())?;
    }
    out.note_held(false);
    Ok(())
}

trait WriteFrame {
    fn write_frame(&mut self, frame: &Frame) -> Result<(), PlayError>;
    fn note_held(&mut self, held: bool);
}

impl WriteFrame for Touch {
    fn write_frame(&mut self, frame: &Frame) -> Result<(), PlayError> {
        Touch::write_frame(self, frame).map_err(|_| PlayError::Blocked(Status::Closed))
    }

    fn note_held(&mut self, held: bool) {
        Touch::note_held(self, held);
    }
}

#[cfg(test)]
struct Memory {
    frames: Vec<Vec<[u8; crate::input::EVENT_SIZE]>>,
    held: bool,
}

#[cfg(test)]
impl WriteFrame for Memory {
    fn write_frame(&mut self, frame: &Frame) -> Result<(), PlayError> {
        self.frames.push(frame.events.clone());
        Ok(())
    }

    fn note_held(&mut self, held: bool) {
        self.held = held;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn groups_contacts_that_share_a_frame() {
        let steps = vec![
            finger(true, 400, 0, 520),
            finger(true, 864, 1, 640),
            Step::Sleep { ms: 17 },
            finger(false, 500, 0, 530),
            finger(false, 764, 1, 650),
            Step::Up { id: 0 },
            Step::Up { id: 1 },
        ];
        assert_eq!(
            beats(&steps),
            vec![
                Beat::Frame {
                    contacts: vec![felt(true, 400, 0, 520), felt(true, 864, 1, 640)],
                },
                Beat::Sleep(17),
                Beat::Frame {
                    contacts: vec![felt(false, 500, 0, 530), felt(false, 764, 1, 650)],
                },
                Beat::Up(0),
                Beat::Up(1),
            ]
        );
    }

    #[test]
    fn tap_ends_with_the_empty_lift() {
        let steps = vec![
            finger(true, 632, 0, 248),
            Step::Sleep { ms: 0 },
            finger(false, 632, 0, 410),
            Step::Up { id: 0 },
        ];
        let mut memory = Memory {
            frames: Vec::new(),
            held: false,
        };
        play_on(&steps, &mut memory).unwrap();
        let lengths: Vec<_> = memory.frames.iter().map(Vec::len).collect();
        assert_eq!(lengths, vec![10, 9, 3]);
        assert!(!memory.held);
        assert_eq!(key_code(&memory.frames[0][8]), 0x14a);
        assert!(memory.frames[1]
            .iter()
            .all(|event| key_code(event) != 0x14a));
        assert_eq!(key_code(&memory.frames[2][1]), 0x14a);
        assert_eq!(event_value(&memory.frames[2][1]), 0);
    }

    #[test]
    fn rejects_invalid_later_steps_without_writing_a_frame() {
        for (later_step, expected) in [
            (
                finger(false, -1, 0, 410),
                PlayError::Axis(crate::input::AxisOutOfRange {
                    axis: "x",
                    pixel: -1,
                }),
            ),
            (Step::Sleep { ms: MAX_SLEEP_MS }, PlayError::TooLong),
        ] {
            let mut memory = Memory {
                frames: Vec::new(),
                held: false,
            };
            let steps = [
                finger(true, 632, 0, 248),
                Step::Sleep { ms: 17 },
                later_step,
            ];
            assert_eq!(play_on(&steps, &mut memory), Err(expected));
            assert!(memory.frames.is_empty());
            assert!(!memory.held);
        }
    }

    fn finger(down: bool, x: i32, id: i32, pressure: i32) -> Step {
        let contact = felt(down, x, id, pressure);
        if down {
            Step::Down {
                x: contact.x,
                y: contact.y,
                id: contact.id,
                pressure: contact.pressure,
                major: contact.major,
                minor: contact.minor,
                orientation: contact.orientation,
            }
        } else {
            Step::Move {
                x: contact.x,
                y: contact.y,
                id: contact.id,
                pressure: contact.pressure,
                major: contact.major,
                minor: contact.minor,
                orientation: contact.orientation,
            }
        }
    }

    fn felt(down: bool, x: i32, id: i32, pressure: i32) -> Contact {
        Contact {
            id,
            x,
            y: 1600,
            down,
            pressure,
            major: 171,
            minor: 154,
            orientation: -22,
        }
    }

    fn key_code(event: &[u8; crate::input::EVENT_SIZE]) -> u16 {
        u16::from_le_bytes([event[18], event[19]])
    }

    fn event_value(event: &[u8; crate::input::EVENT_SIZE]) -> i32 {
        i32::from_le_bytes([event[20], event[21], event[22], event[23]])
    }
}
