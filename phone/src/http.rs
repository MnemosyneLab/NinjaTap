//! HTTPS routes for the Android player.
//!
//! The bearer token is checked. A subnet allow-list is not applied yet.

use std::error::Error;
use std::io::{self, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::time::Duration;

use axum::body::{to_bytes, Body};
use axum::extract::{Query, Request, State};
use axum::http::{header, Method, StatusCode};
use axum::response::Response;
use axum::Router;
use futures_util::StreamExt;
use http_body_util::{BodyExt, LengthLimitError};
use serde::Deserialize;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use tokio::time::timeout;
use tokio_util::io::ReaderStream;

use crate::auth;
use crate::capture::{self, CaptureError};
use crate::clipboard;
use crate::play::{self, PlayError};
use crate::protocol::{InjectRequest, InjectResponse, Status, Step};
use crate::screen::{self, Rotation, ScreenError};
use crate::storage;
use crate::tls;

type HttpResponse = Response<Body>;

const MAX_BODY_BYTES: usize = 256 * 1024;
const BODY_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Clone)]
struct ServerState {
    secret: Arc<str>,
    capture: Arc<Semaphore>,
    touch: Arc<Semaphore>,
    clipboard: Arc<Semaphore>,
    transfer: Arc<Semaphore>,
}

#[tokio::main(flavor = "current_thread")]
pub async fn serve(bind: &str, secret: &str, identity: &Path) -> std::io::Result<()> {
    let (config, fingerprint) = tls::load(identity)?;
    let listener = TcpListener::bind(bind)?;
    let server = axum_server::tls_rustls::from_tcp_rustls(listener, config)?;
    println!("NINJATAP_READY {fingerprint}");
    server.serve(router(secret).into_make_service()).await
}

fn router(secret: &str) -> Router {
    Router::new().fallback(handle).with_state(ServerState {
        secret: secret.into(),
        capture: Arc::new(Semaphore::new(1)),
        touch: Arc::new(Semaphore::new(1)),
        clipboard: Arc::new(Semaphore::new(1)),
        transfer: Arc::new(Semaphore::new(1)),
    })
}

async fn handle(State(state): State<ServerState>, request: Request) -> HttpResponse {
    let authorization = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok());
    if !auth::bearer_matches(authorization, &state.secret) {
        return json_status(Status::Unauthorized, 401);
    }
    let (parts, body) = request.into_parts();
    if parts.uri.path() == "/files" && matches!(parts.method, Method::GET | Method::PUT) {
        let Ok(Query(FilePath { path })) = Query::try_from_uri(&parts.uri) else {
            return text("provide a file path under /sdcard\n", 400);
        };
        let Ok(permit) = state.transfer.try_acquire_owned() else {
            return text("file transfer busy\n", 503);
        };
        let root = PathBuf::from(storage::ROOT);
        if parts.method == Method::GET {
            return download_file(root, path, permit).await;
        }
        let Some(size) = parts
            .headers
            .get(header::CONTENT_LENGTH)
            .and_then(|length| length.to_str().ok())
            .and_then(|length| length.parse::<u64>().ok())
        else {
            return text("file size is required\n", 411);
        };
        return upload_file(root, path, size, body).await;
    }
    let mut payload = Default::default();
    let operation = match (&parts.method, parts.uri.path()) {
        (&Method::GET, "/screencap") => Operation::Screencap,
        (&Method::GET, "/screen") => Operation::Screen,
        (&Method::GET, "/clipboard") => Operation::ReadClipboard,
        (
            &Method::POST,
            path @ ("/inject" | "/clipboard" | "/key" | "/screen/lock" | "/screen/unlock"),
        ) => {
            payload = match timeout(BODY_TIMEOUT, to_bytes(body, MAX_BODY_BYTES)).await {
                Ok(Ok(payload)) => payload,
                Ok(Err(error)) if error.source().is_some_and(|e| e.is::<LengthLimitError>()) => {
                    return text("request body exceeds 256 KiB\n", 413);
                }
                Ok(Err(_)) => return text("bad request\n", 400),
                Err(_) => return text("request body timed out\n", 408),
            };
            match path {
                "/inject" => Operation::Inject,
                "/key" => Operation::Key,
                "/screen/lock" | "/screen/unlock" => {
                    if !payload.is_empty() {
                        return text("screen control requires an empty request body\n", 400);
                    }
                    Operation::ScreenControl(if path == "/screen/lock" { b'L' } else { b'U' })
                }
                _ => Operation::WriteClipboard,
            }
        }
        _ => return text("not found\n", 404),
    };

    // These operations use separate resources. Reject overlap within each
    // category without queuing work on the phone.
    let semaphore = match operation {
        Operation::Screencap | Operation::Screen => state.capture.clone(),
        Operation::Inject | Operation::Key | Operation::ScreenControl(_) => state.touch,
        Operation::ReadClipboard | Operation::WriteClipboard => state.clipboard,
    };
    let Ok(permit) = semaphore.try_acquire_owned() else {
        return text("device busy\n", 503);
    };
    // Keep screenshots and remote input out of the PIN entry sequence.
    let capture_permit = if matches!(operation, Operation::ScreenControl(_)) {
        let Ok(permit) = state.capture.try_acquire_owned() else {
            return text("device busy\n", 503);
        };
        Some(permit)
    } else {
        None
    };
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        let _capture_permit = capture_permit;
        match operation {
            Operation::Screencap => screencap(),
            Operation::Screen => screen_geometry(),
            Operation::ReadClipboard => read_clipboard(),
            Operation::Inject => inject(&payload),
            Operation::Key => press_key(&payload),
            Operation::ScreenControl(command) => control_screen(command),
            Operation::WriteClipboard => write_clipboard(&payload),
        }
    })
    .await
    .unwrap_or_else(|_| text("device operation failed\n", 500))
}

enum Operation {
    Screencap,
    Screen,
    ReadClipboard,
    Inject,
    Key,
    ScreenControl(u8),
    WriteClipboard,
}

fn control_screen(command: u8) -> HttpResponse {
    let response = screen::control(command);
    let (status, code) = match response.as_deref() {
        Ok("ok") => ("ok", 200),
        Ok("screen_pin_required") => ("screen_pin_required", 409),
        Ok("screen_pin_reset_required") => ("screen_pin_reset_required", 409),
        Ok("screen_pin_keypad_unavailable") => ("screen_pin_keypad_unavailable", 409),
        Ok("screen_pin_unavailable") => ("screen_pin_unavailable", 409),
        Ok("screen_wake_failed") => ("screen_wake_failed", 502),
        Ok("screen_lock_failed") => ("screen_lock_failed", 502),
        Ok("screen_unlock_failed") => ("screen_unlock_failed", 502),
        Ok("screen_control_unavailable") => ("screen_control_unavailable", 503),
        Err(error) if error.kind() == io::ErrorKind::NotConnected => {
            ("screen_control_unavailable", 503)
        }
        Err(error)
            if matches!(
                error.kind(),
                io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
            ) =>
        {
            ("screen_control_timeout", 504)
        }
        _ => ("screen_control_failed", 502),
    };
    bytes(
        serde_json::json!({ "status": status })
            .to_string()
            .into_bytes(),
        "application/json",
        code,
    )
}

#[derive(Deserialize)]
struct KeyRequest {
    key: NavigationKey,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum NavigationKey {
    Back,
    Home,
}

fn press_key(body: &[u8]) -> HttpResponse {
    let Ok(request) = serde_json::from_slice::<KeyRequest>(body) else {
        return text("key must be back or home\n", 400);
    };
    if let Err(response) = ready() {
        return response;
    }
    let key = match request.key {
        NavigationKey::Back => "KEYCODE_BACK",
        NavigationKey::Home => "KEYCODE_HOME",
    };
    match Command::new("/system/bin/input")
        .args(["keyevent", key])
        .status()
    {
        Ok(status) if status.success() => json_status(Status::Ok, 200),
        _ => text("could not send Android navigation key\n", 500),
    }
}

#[derive(Deserialize)]
struct FilePath {
    path: PathBuf,
}

async fn download_file(root: PathBuf, path: PathBuf, permit: OwnedSemaphorePermit) -> HttpResponse {
    match tokio::task::spawn_blocking(move || storage::read(&root, &path)).await {
        Ok(Ok((file, size))) => {
            let stream =
                ReaderStream::new(tokio::fs::File::from_std(file).take(size)).map(move |chunk| {
                    let _ = &permit;
                    chunk
                });
            Response::builder()
                .header(header::CONTENT_TYPE, "application/octet-stream")
                .header(header::CONTENT_LENGTH, size)
                .body(Body::from_stream(stream))
                .unwrap()
        }
        Ok(Err(error)) => file_error(error),
        Err(_) => text("could not open shared-storage file\n", 500),
    }
}

async fn upload_file(root: PathBuf, path: PathBuf, size: u64, mut body: Body) -> HttpResponse {
    let (upload, file) =
        match tokio::task::spawn_blocking(move || storage::Upload::start(&root, &path)).await {
            Ok(Ok(pair)) => pair,
            Ok(Err(error)) => return file_error(error),
            Err(_) => return text("could not start upload\n", 500),
        };
    let mut file = tokio::fs::File::from_std(file);
    let mut remaining = size;
    loop {
        let frame = match timeout(BODY_TIMEOUT, body.frame()).await {
            Ok(Some(Ok(frame))) => frame,
            Ok(None) => break,
            Ok(Some(Err(_))) => return text("incomplete upload\n", 400),
            Err(_) => return text("upload timed out\n", 408),
        };
        if let Ok(chunk) = frame.into_data() {
            let Some(rest) = remaining.checked_sub(chunk.len() as u64) else {
                return text("upload size does not match\n", 400);
            };
            if let Err(error) = file.write_all(&chunk).await {
                return file_error(error);
            }
            remaining = rest;
        }
    }
    if remaining != 0 {
        return text("incomplete upload\n", 400);
    }
    if let Err(error) = file.sync_all().await {
        return file_error(error);
    }
    drop(file);
    match tokio::task::spawn_blocking(move || {
        let path = upload.finish()?;
        // The Android service keeps reading the player's stdout after NINJATAP_READY.
        let path = serde_json::to_string(&path.to_string_lossy()).map_err(io::Error::other)?;
        let _ = writeln!(io::stdout().lock(), "NINJATAP_SCAN {path}");
        Ok(())
    })
    .await
    {
        Ok(Ok(())) => json_status(Status::Ok, 201),
        Ok(Err(error)) => file_error(error),
        Err(_) => text("could not finish upload\n", 500),
    }
}

fn file_error(error: io::Error) -> HttpResponse {
    let (message, code) = match error.kind() {
        io::ErrorKind::NotFound => ("file or parent directory not found\n", 404),
        io::ErrorKind::AlreadyExists => ("destination file already exists\n", 409),
        io::ErrorKind::PermissionDenied => ("shared-storage permission denied\n", 403),
        io::ErrorKind::InvalidInput | io::ErrorKind::NotADirectory => {
            ("invalid shared-storage file path\n", 400)
        }
        _ => {
            eprintln!("file transfer: {error}");
            ("shared-storage file operation failed\n", 500)
        }
    };
    text(message, code)
}

fn screencap() -> HttpResponse {
    let rotation = match ready() {
        Ok(rotation) => rotation,
        Err(response) => return response,
    };
    let png = match capture::png() {
        Ok(png) => png,
        Err(CaptureError::Failed) => return text("screencap failed\n", 500),
    };
    match ready() {
        Ok(after) if rotation == after && capture::size(&png) == Some(rotation.size()) => {
            let mut response = bytes(png, "image/png", 200);
            response
                .headers_mut()
                .insert("x-ninjatap-rotation", (rotation as u16).into());
            response
        }
        Ok(_) => json_status(Status::RotationChanged, 409),
        Err(response) => response,
    }
}

fn screen_geometry() -> HttpResponse {
    let rotation = match ready() {
        Ok(rotation) => rotation,
        Err(response) => return response,
    };
    let (width, height) = rotation.size();
    let body = serde_json::json!({
        "status": "ok",
        "rotation": rotation as u8,
        "width": width,
        "height": height,
    });
    bytes(body.to_string().into_bytes(), "application/json", 200)
}

fn touch_sequence(steps: &mut [Step], rotation: Rotation) -> bool {
    for step in steps {
        if let Step::Down { x, y, .. } | Step::Move { x, y, .. } = step {
            let Some((native_x, native_y)) = rotation.native_point(*x, *y) else {
                return false;
            };
            (*x, *y) = (native_x, native_y);
        }
    }
    true
}

fn inject(body: &[u8]) -> HttpResponse {
    let mut request: InjectRequest = match serde_json::from_slice(body) {
        Ok(request) => request,
        Err(_) => return text("bad json\n", 400),
    };
    let Some(expected) = Rotation::from_android(request.rotation) else {
        return text("rotation must be between 0 and 3\n", 400);
    };
    let rotation = match ready() {
        Ok(rotation) => rotation,
        Err(response) => return response,
    };
    if rotation != expected {
        return json_status(Status::RotationChanged, 409);
    }
    if !touch_sequence(&mut request.sequence, rotation) {
        return text("coordinate out of range\n", 400);
    }
    match play::play(&request.sequence) {
        Ok(()) => json_status(Status::Ok, 200),
        Err(PlayError::Blocked(status)) => json_status(status, 200),
        Err(PlayError::Axis(_)) => text("coordinate out of range\n", 400),
        Err(PlayError::TooLong) => text("gesture exceeds 15000 ms\n", 400),
        Err(PlayError::TimedOut) => text("gesture playback timed out\n", 504),
    }
}

#[derive(Deserialize)]
struct ClipWrite {
    text: String,
}

fn read_clipboard() -> HttpResponse {
    match clipboard::read() {
        Ok(text) => clip_body("ok", Some(text), None),
        Err(error) => clip_body("unavailable", None, Some(error.0)),
    }
}

fn write_clipboard(body: &[u8]) -> HttpResponse {
    let request: ClipWrite = match serde_json::from_slice(body) {
        Ok(request) => request,
        Err(_) => return text("bad json\n", 400),
    };
    match clipboard::write(&request.text) {
        Ok(()) => clip_body("ok", None, None),
        Err(error) => clip_body("unavailable", None, Some(error.0)),
    }
}

fn clip_body(status: &str, text: Option<String>, detail: Option<String>) -> HttpResponse {
    let mut body = serde_json::Map::new();
    body.insert("status".into(), status.into());
    if let Some(text) = text {
        body.insert("text".into(), text.into());
    }
    if let Some(detail) = detail {
        body.insert("detail".into(), detail.into());
    }
    bytes(
        serde_json::Value::Object(body).to_string().into_bytes(),
        "application/json",
        200,
    )
}

fn ready() -> Result<Rotation, HttpResponse> {
    match screen::ensure_ready() {
        Ok(rotation) => Ok(rotation),
        Err(ScreenError::Unreadable) => Err(text("screen check failed\n", 500)),
        Err(ScreenError::Blocked(status)) => Err(json_status(status, 200)),
    }
}

fn json_status(status: Status, code: u16) -> HttpResponse {
    let body = serde_json::to_string(&InjectResponse { status }).unwrap();
    bytes(body.into_bytes(), "application/json", code)
}

fn text(body: &str, code: u16) -> HttpResponse {
    bytes(body.as_bytes().to_vec(), "text/plain; charset=utf-8", code)
}

fn bytes(body: Vec<u8>, content_type: &str, code: u16) -> HttpResponse {
    Response::builder()
        .status(StatusCode::from_u16(code).unwrap())
        .header(header::CONTENT_TYPE, content_type)
        .body(Body::from(body))
        .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn file_transfer_streams_and_discards_incomplete_uploads() {
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path().to_path_buf();
        let path = PathBuf::from("/sdcard/测试 & photo.png");
        let data = vec![0x89; MAX_BODY_BYTES + 1];
        let length = data.len() as u64;

        let short = upload_file(
            root.clone(),
            path.clone(),
            length + 1,
            Body::from(data.clone()),
        )
        .await;
        assert_eq!(short.status(), StatusCode::BAD_REQUEST);
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 0);

        let complete =
            upload_file(root.clone(), path.clone(), length, Body::from(data.clone())).await;
        assert_eq!(complete.status(), StatusCode::CREATED);
        let semaphore = Arc::new(Semaphore::new(1));
        let permit = semaphore.clone().try_acquire_owned().unwrap();
        let download = download_file(root, path, permit).await;
        assert_eq!(
            download.headers()[header::CONTENT_LENGTH],
            length.to_string()
        );
        assert_eq!(semaphore.available_permits(), 0);
        assert_eq!(
            to_bytes(download.into_body(), data.len()).await.unwrap(),
            data
        );
        assert_eq!(semaphore.available_permits(), 1);
    }

    #[tokio::test]
    async fn rejects_oversized_bodies_before_using_the_device() {
        let response = handle(
            State(ServerState {
                secret: "fixture".into(),
                capture: Arc::new(Semaphore::new(1)),
                touch: Arc::new(Semaphore::new(0)),
                clipboard: Arc::new(Semaphore::new(1)),
                transfer: Arc::new(Semaphore::new(1)),
            }),
            Request::builder()
                .method(Method::POST)
                .uri("/inject?unused=1")
                .header(header::AUTHORIZATION, "Bearer fixture")
                .body(Body::from(vec![b' '; MAX_BODY_BYTES + 1]))
                .unwrap(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
    }

    #[cfg(not(target_os = "android"))]
    #[tokio::test]
    async fn screenshot_touch_and_clipboard_have_independent_limits() {
        let state = ServerState {
            secret: "fixture".into(),
            capture: Arc::new(Semaphore::new(1)),
            touch: Arc::new(Semaphore::new(1)),
            clipboard: Arc::new(Semaphore::new(1)),
            transfer: Arc::new(Semaphore::new(1)),
        };
        let touch = state.touch.clone().try_acquire_owned().unwrap();
        let request = || Request::builder().header(header::AUTHORIZATION, "Bearer fixture");
        let post = |uri| {
            request()
                .method(Method::POST)
                .uri(uri)
                .body(Body::from("{}"))
                .unwrap()
        };
        assert_eq!(
            handle(State(state.clone()), post("/inject")).await.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            handle(
                State(state.clone()),
                request()
                    .method(Method::POST)
                    .uri("/screen/unlock")
                    .body(Body::empty())
                    .unwrap()
            )
            .await
            .status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            handle(State(state.clone()), post("/clipboard"))
                .await
                .status(),
            StatusCode::BAD_REQUEST
        );

        let _clipboard = state.clipboard.clone().try_acquire_owned().unwrap();
        let clipboard_read = request().uri("/clipboard").body(Body::empty()).unwrap();
        assert_eq!(
            handle(State(state.clone()), clipboard_read).await.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        let screenshot = || request().uri("/screencap").body(Body::empty()).unwrap();
        let capture = handle(State(state.clone()), screenshot()).await;
        // On the host, the request reaches the Android screen check.
        assert_eq!(capture.status(), StatusCode::INTERNAL_SERVER_ERROR);

        let _capture = state.capture.clone().try_acquire_owned().unwrap();
        drop(touch);
        assert_eq!(
            handle(State(state.clone()), post("/inject")).await.status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            handle(State(state), screenshot()).await.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
    }

    #[tokio::test]
    async fn screen_control_rejects_unauthenticated_requests_and_payloads() {
        let state = ServerState {
            secret: "fixture".into(),
            capture: Arc::new(Semaphore::new(1)),
            touch: Arc::new(Semaphore::new(1)),
            clipboard: Arc::new(Semaphore::new(1)),
            transfer: Arc::new(Semaphore::new(1)),
        };
        for path in ["/screen/lock", "/screen/unlock"] {
            let post = || Request::builder().method(Method::POST).uri(path);
            let unauthorized = post().body(Body::empty()).unwrap();
            let with_body = post()
                .header(header::AUTHORIZATION, "Bearer fixture")
                .body(Body::from("{}"))
                .unwrap();
            assert_eq!(
                handle(State(state.clone()), unauthorized).await.status(),
                StatusCode::UNAUTHORIZED
            );
            assert_eq!(
                handle(State(state.clone()), with_body).await.status(),
                StatusCode::BAD_REQUEST
            );
        }
    }
}
