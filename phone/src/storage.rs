//! File access within the primary Android shared-storage volume.

use std::ffi::{OsStr, OsString};
use std::fs::File;
use std::io;
use std::path::{Component, Path, PathBuf};

use ring::rand::{SecureRandom, SystemRandom};
use rustix::fd::OwnedFd;
use rustix::fs::{self, AtFlags, Mode, OFlags, RenameFlags};
use rustix::io::Errno;

pub(crate) const ROOT: &str = "/storage/emulated/0";
const STAGING_PREFIX: &str = ".ninjatap-upload-";

fn relative_path(remote: &Path) -> io::Result<&Path> {
    if remote.is_absolute() {
        remote
            .strip_prefix("/sdcard")
            .or_else(|_| remote.strip_prefix(ROOT))
            .map_err(|_| bad_path())
    } else {
        Ok(remote)
    }
}

fn parent(root: &Path, relative: &Path) -> io::Result<(OwnedFd, OsString)> {
    let mut components = relative.components().peekable();
    let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    // Each lookup stays relative to an already opened directory.
    let mut directory = fs::open(root, flags, Mode::empty())?;
    while let Some(component) = components.next() {
        let Component::Normal(name) = component else {
            return Err(bad_path());
        };
        if name
            .as_encoded_bytes()
            .starts_with(STAGING_PREFIX.as_bytes())
        {
            return Err(bad_path());
        }
        if components.peek().is_none() {
            return Ok((directory, name.to_owned()));
        }
        directory = fs::openat(&directory, name, flags, Mode::empty())?;
    }
    Err(bad_path())
}

fn bad_path() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidInput,
        "provide a file path under /sdcard",
    )
}

pub(crate) fn read(root: &Path, remote: &Path) -> io::Result<(File, u64)> {
    let (directory, name) = parent(root, relative_path(remote)?)?;
    let flags = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC;
    let file = File::from(fs::openat(directory, name, flags, Mode::empty())?);
    let info = file.metadata()?;
    if !info.is_file() {
        return Err(bad_path());
    }
    Ok((file, info.len()))
}

pub(crate) struct Upload {
    directory: OwnedFd,
    target: OsString,
    pending: String,
    published_path: PathBuf,
}

impl Upload {
    pub(crate) fn start(root: &Path, remote: &Path) -> io::Result<(Self, File)> {
        let relative = relative_path(remote)?;
        let (directory, target) = parent(root, relative)?;
        match fs::statat(&directory, &target, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(_) => return Err(Errno::EXIST.into()),
            Err(Errno::NOENT) => {}
            Err(error) => return Err(error.into()),
        }
        let mut random = [0; 16];
        SystemRandom::new()
            .fill(&mut random)
            .map_err(|_| io::Error::other("could not create an upload file name"))?;
        let pending = format!("{STAGING_PREFIX}{:032x}", u128::from_ne_bytes(random));
        let flags = OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC;
        let file = fs::openat(&directory, pending.as_str(), flags, Mode::RUSR | Mode::WUSR)?;
        Ok((
            Self {
                directory,
                target,
                pending,
                published_path: root.join(relative),
            },
            File::from(file),
        ))
    }

    pub(crate) fn finish(self) -> io::Result<PathBuf> {
        fs::renameat_with(
            &self.directory,
            OsStr::new(&self.pending),
            &self.directory,
            &self.target,
            RenameFlags::NOREPLACE,
        )?;
        Ok(self.published_path.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::os::unix::fs::symlink;

    #[test]
    fn shared_paths_accept_both_aliases_and_reject_escapes() {
        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        std::fs::write(root.path().join("测试 & image.png"), b"original").unwrap();
        std::fs::write(outside.path().join("private"), b"private").unwrap();
        symlink(outside.path(), root.path().join("link")).unwrap();
        symlink(
            outside.path().join("private"),
            root.path().join("file-link"),
        )
        .unwrap();
        for path in [
            "/sdcard/测试 & image.png",
            "/storage/emulated/0/测试 & image.png",
        ] {
            let (mut file, size) = read(root.path(), Path::new(path)).unwrap();
            let mut contents = Vec::new();
            file.read_to_end(&mut contents).unwrap();
            assert_eq!((size, contents.as_slice()), (8, b"original".as_slice()));
        }
        for path in [
            "/data/private",
            "/sdcard/../private",
            "/sdcard/link/private",
            "/sdcard/file-link",
        ] {
            assert!(read(root.path(), Path::new(path)).is_err(), "{path}");
            assert!(
                Upload::start(root.path(), Path::new(path)).is_err(),
                "{path}"
            );
        }
    }

    #[test]
    fn aborted_uploads_are_removed_and_commit_will_not_overwrite() {
        let root = tempfile::tempdir().unwrap();
        let remote = Path::new("/sdcard/photo.png");
        let (upload, mut file) = Upload::start(root.path(), remote).unwrap();
        file.write_all(b"partial").unwrap();
        assert!(!root.path().join("photo.png").exists());
        drop(file);
        drop(upload);
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 0);

        let (upload, mut file) = Upload::start(root.path(), remote).unwrap();
        file.write_all(b"complete").unwrap();
        drop(file);
        assert_eq!(upload.finish().unwrap(), root.path().join("photo.png"));
        assert_eq!(
            std::fs::read(root.path().join("photo.png")).unwrap(),
            b"complete"
        );

        let other = Path::new("/sdcard/existing");
        let (upload, _) = Upload::start(root.path(), other).unwrap();
        std::fs::write(root.path().join("existing"), b"keep").unwrap();
        assert_eq!(
            upload.finish().unwrap_err().kind(),
            io::ErrorKind::AlreadyExists
        );
        assert_eq!(
            std::fs::read(root.path().join("existing")).unwrap(),
            b"keep"
        );
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 2);
    }
}

impl Drop for Upload {
    fn drop(&mut self) {
        let _ = fs::unlinkat(&self.directory, self.pending.as_str(), AtFlags::empty());
    }
}
