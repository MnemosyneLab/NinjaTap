//! Constants for this one HONOR DNY-NX9. Other phones are out of scope.

pub const DISPLAY_ID: &str = "4630946363286114434";
pub const DEVICE_PATH: &str = "/dev/input/event6";
pub const WIDTH: i32 = 1264;
pub const HEIGHT: i32 = 2736;
pub const SCALE: i32 = 8;
pub const AXIS_X_MAX: i32 = 10111;
pub const AXIS_Y_MAX: i32 = 21887;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_frame_pixels_fit_the_axes() {
        assert!((WIDTH - 1) * SCALE <= AXIS_X_MAX);
        assert!((HEIGHT - 1) * SCALE <= AXIS_Y_MAX);
    }
}
