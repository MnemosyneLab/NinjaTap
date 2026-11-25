//! One touch frame for `/dev/input/event6` on this phone.
//!
//! Each contact ends with `SYN_MT_REPORT`. The frame ends with `SYN_REPORT`.
//! `BTN_TOUCH` is written only when the caller says the contact state changed.
//! A lift is an empty report followed by `BTN_TOUCH 0`.

use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};

use crate::device;

pub const EVENT_SIZE: usize = 24;
pub const PATH: &str = device::DEVICE_PATH;

const EV_SYN: u16 = 0;
const EV_KEY: u16 = 1;
const EV_ABS: u16 = 3;
const SYN_REPORT: u16 = 0;
const SYN_MT_REPORT: u16 = 2;
const BTN_TOUCH: u16 = 0x14a;
const ABS_MT_TOUCH_MAJOR: u16 = 0x30;
const ABS_MT_TOUCH_MINOR: u16 = 0x31;
const ABS_MT_ORIENTATION: u16 = 0x34;
const ABS_MT_POSITION_X: u16 = 0x35;
const ABS_MT_POSITION_Y: u16 = 0x36;
const ABS_MT_TRACKING_ID: u16 = 0x39;
const ABS_MT_PRESSURE: u16 = 0x3a;
const BTN_TOUCH_BYTE: usize = (BTN_TOUCH as usize) / 8;
const BTN_TOUCH_BIT: u8 = 1 << ((BTN_TOUCH as usize) % 8);
const EVIOCGKEY_96: u64 = (2 << 30) | ((b'E' as u64) << 8) | 0x18 | (96 << 16);

static TOUCH_FD: AtomicI32 = AtomicI32::new(-1);
static HELD: AtomicBool = AtomicBool::new(false);

#[derive(Debug, PartialEq, Eq)]
pub struct AxisOutOfRange {
    pub axis: &'static str,
    pub pixel: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Contact {
    pub id: i32,
    pub x: i32,
    pub y: i32,
    pub down: bool,
    pub pressure: i32,
    pub major: i32,
    pub minor: i32,
    pub orientation: i32,
}

pub struct Frame {
    pub events: Vec<[u8; EVENT_SIZE]>,
}

pub struct FrameBuilder {
    events: Vec<[u8; EVENT_SIZE]>,
}

impl FrameBuilder {
    pub fn new() -> Self {
        Self { events: Vec::new() }
    }

    pub fn contact(&mut self, contact: Contact) -> Result<(), AxisOutOfRange> {
        let (x, y) = position(contact.x, contact.y)?;
        self.events.extend([
            event(EV_ABS, ABS_MT_TRACKING_ID, contact.id),
            event(EV_ABS, ABS_MT_POSITION_X, x),
            event(EV_ABS, ABS_MT_POSITION_Y, y),
            event(EV_ABS, ABS_MT_PRESSURE, contact.pressure),
            event(EV_ABS, ABS_MT_TOUCH_MAJOR, contact.major),
            event(EV_ABS, ABS_MT_TOUCH_MINOR, contact.minor),
            event(EV_ABS, ABS_MT_ORIENTATION, contact.orientation),
            event(EV_SYN, SYN_MT_REPORT, 0),
        ]);
        Ok(())
    }

    pub fn finish(mut self, button_down: bool) -> Frame {
        if button_down {
            self.events.push(event(EV_KEY, BTN_TOUCH, 1));
        }
        self.events.push(event(EV_SYN, SYN_REPORT, 0));
        Frame {
            events: self.events,
        }
    }
}

pub(crate) fn position(x: i32, y: i32) -> Result<(i32, i32), AxisOutOfRange> {
    Ok((
        axis("x", x, device::AXIS_X_MAX)?,
        axis("y", y, device::AXIS_Y_MAX)?,
    ))
}

pub fn lift_frame() -> Frame {
    Frame {
        events: vec![
            event(EV_SYN, SYN_MT_REPORT, 0),
            event(EV_KEY, BTN_TOUCH, 0),
            event(EV_SYN, SYN_REPORT, 0),
        ],
    }
}

pub struct Touch {
    file: File,
}

impl Touch {
    pub fn open() -> io::Result<Self> {
        let file = OpenOptions::new().read(true).write(true).open(PATH)?;
        TOUCH_FD.store(file.as_raw_fd(), Ordering::Release);
        Ok(Self { file })
    }

    pub fn finger_present(&self) -> bool {
        let mut bits = [0u8; 96];
        let rc = unsafe { ioctl(self.file.as_raw_fd(), EVIOCGKEY_96, bits.as_mut_ptr()) };
        if rc < 0 {
            return false;
        }
        bits[BTN_TOUCH_BYTE] & BTN_TOUCH_BIT != 0
    }

    pub fn write_frame(&mut self, frame: &Frame) -> io::Result<()> {
        for event in &frame.events {
            self.file.write_all(event)?;
        }
        self.file.flush()
    }

    pub fn note_held(&self, held: bool) {
        HELD.store(held, Ordering::Release);
    }
}

impl Drop for Touch {
    fn drop(&mut self) {
        if HELD.swap(false, Ordering::AcqRel) {
            let _ = self.write_frame(&lift_frame());
        }
        TOUCH_FD.store(-1, Ordering::Release);
    }
}

pub fn install_exit_lift() {
    #[cfg(target_os = "android")]
    unsafe {
        signal(2, on_signal as *const () as usize);
        signal(15, on_signal as *const () as usize);
    }
}

#[cfg(target_os = "android")]
unsafe extern "C" fn on_signal(sig: i32) {
    lift_held_fd();
    unsafe {
        signal(sig, 0);
        raise(sig);
    }
}

#[cfg(target_os = "android")]
fn lift_held_fd() {
    let fd = TOUCH_FD.load(Ordering::Acquire);
    if fd < 0 || !HELD.swap(false, Ordering::AcqRel) {
        return;
    }
    let mut stamp = Timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    unsafe { clock_gettime(0, &mut stamp) };
    let sec = stamp.tv_sec as u64;
    let usec = (stamp.tv_nsec / 1000) as u64;
    let mut bytes = [0u8; EVENT_SIZE * 3];
    fill_event(
        &mut bytes[0..EVENT_SIZE],
        sec,
        usec,
        EV_SYN,
        SYN_MT_REPORT,
        0,
    );
    fill_event(
        &mut bytes[EVENT_SIZE..EVENT_SIZE * 2],
        sec,
        usec,
        EV_KEY,
        BTN_TOUCH,
        0,
    );
    fill_event(
        &mut bytes[EVENT_SIZE * 2..],
        sec,
        usec,
        EV_SYN,
        SYN_REPORT,
        0,
    );
    let mut off = 0;
    while off < bytes.len() {
        let wrote = unsafe { write(fd, bytes.as_ptr().add(off).cast(), bytes.len() - off) };
        if wrote < 0 {
            let err = unsafe { *errno_location() };
            if err == 4 {
                continue;
            }
            break;
        }
        if wrote == 0 {
            break;
        }
        off += wrote as usize;
    }
}

#[cfg(target_os = "android")]
#[repr(C)]
struct Timespec {
    tv_sec: i64,
    tv_nsec: i64,
}

#[cfg(target_os = "android")]
unsafe extern "C" {
    fn clock_gettime(clock: i32, stamp: *mut Timespec) -> i32;
    fn write(fd: i32, buf: *const std::ffi::c_void, count: usize) -> isize;
    fn ioctl(fd: i32, request: u64, arg: *mut u8) -> i32;
    fn signal(sig: i32, handler: usize) -> usize;
    fn raise(sig: i32) -> i32;
    fn __errno() -> *mut i32;
}

#[cfg(target_os = "android")]
fn errno_location() -> *mut i32 {
    unsafe { __errno() }
}

#[cfg(not(target_os = "android"))]
unsafe fn ioctl(_fd: i32, _request: u64, _arg: *mut u8) -> i32 {
    -1
}

fn axis(name: &'static str, pixel: i32, max_axis: i32) -> Result<i32, AxisOutOfRange> {
    if pixel < 0 {
        return Err(AxisOutOfRange { axis: name, pixel });
    }
    let raw = pixel
        .checked_mul(device::SCALE)
        .ok_or(AxisOutOfRange { axis: name, pixel })?;
    if raw > max_axis {
        return Err(AxisOutOfRange { axis: name, pixel });
    }
    Ok(raw)
}

fn event(type_: u16, code: u16, value: i32) -> [u8; EVENT_SIZE] {
    let mut buf = [0u8; EVENT_SIZE];
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    fill_event(
        &mut buf,
        now.as_secs(),
        u64::from(now.subsec_micros()),
        type_,
        code,
        value,
    );
    buf
}

fn fill_event(buf: &mut [u8], sec: u64, usec: u64, type_: u16, code: u16, value: i32) {
    buf[0..8].copy_from_slice(&sec.to_le_bytes());
    buf[8..16].copy_from_slice(&usec.to_le_bytes());
    buf[16..18].copy_from_slice(&type_.to_le_bytes());
    buf[18..20].copy_from_slice(&code.to_le_bytes());
    buf[20..24].copy_from_slice(&value.to_le_bytes());
}

#[cfg(test)]
fn code_value(event: &[u8; EVENT_SIZE]) -> (u16, u16, i32) {
    let type_ = u16::from_le_bytes([event[16], event[17]]);
    let code = u16::from_le_bytes([event[18], event[19]]);
    let value = i32::from_le_bytes([event[20], event[21], event[22], event[23]]);
    (type_, code, value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn targets_the_measured_touch_node() {
        assert_eq!(PATH, "/dev/input/event6");
    }

    fn sample(down: bool) -> Contact {
        Contact {
            id: 0,
            x: 632,
            y: 1500,
            down,
            pressure: 248,
            major: 171,
            minor: 154,
            orientation: -22,
        }
    }

    fn codes(frame: &Frame) -> Vec<(u16, u16, i32)> {
        frame.events.iter().map(code_value).collect()
    }

    #[test]
    fn down_frame_writes_the_given_contact() {
        let mut frame = FrameBuilder::new();
        frame
            .contact(sample(true))
            .unwrap();
        let codes = codes(&frame.finish(true));
        assert_eq!(
            codes,
            vec![
                (EV_ABS, ABS_MT_TRACKING_ID, 0),
                (EV_ABS, ABS_MT_POSITION_X, 5056),
                (EV_ABS, ABS_MT_POSITION_Y, 12000),
                (EV_ABS, ABS_MT_PRESSURE, 248),
                (EV_ABS, ABS_MT_TOUCH_MAJOR, 171),
                (EV_ABS, ABS_MT_TOUCH_MINOR, 154),
                (EV_ABS, ABS_MT_ORIENTATION, -22),
                (EV_SYN, SYN_MT_REPORT, 0),
                (EV_KEY, BTN_TOUCH, 1),
                (EV_SYN, SYN_REPORT, 0),
            ]
        );
    }

    #[test]
    fn move_frame_has_no_button() {
        let mut frame = FrameBuilder::new();
        frame
            .contact(sample(false))
            .unwrap();
        let codes = codes(&frame.finish(false));
        assert_eq!(codes.len(), 9);
        assert_eq!(codes.last().unwrap(), &(EV_SYN, SYN_REPORT, 0));
        assert!(codes.iter().all(|item| item.1 != BTN_TOUCH));
    }

    #[test]
    fn lift_frame_is_an_empty_report() {
        let codes = codes(&lift_frame());
        assert_eq!(
            codes,
            vec![
                (EV_SYN, SYN_MT_REPORT, 0),
                (EV_KEY, BTN_TOUCH, 0),
                (EV_SYN, SYN_REPORT, 0),
            ]
        );
    }

    #[test]
    fn pixels_past_the_axis_max_are_rejected() {
        let mut frame = FrameBuilder::new();
        assert!(frame
            .contact(Contact {
                x: 1264,
                ..sample(true)
            })
            .is_err());
        assert!(frame
            .contact(Contact {
                x: 0,
                y: 2736,
                ..sample(true)
            })
            .is_err());
    }
}
