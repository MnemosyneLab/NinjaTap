//! The private identity the Wi-Fi client pins across player restarts.

use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;

use axum_server::tls_rustls::RustlsConfig;
use rcgen::{generate_simple_self_signed, CertifiedKey};
use rustls::pki_types::{pem::PemObject, CertificateDer, PrivateKeyDer};

pub(crate) fn load(path: &Path) -> io::Result<(RustlsConfig, String)> {
    if !path.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "TLS identity path must be absolute",
        ));
    }
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => generate(path)?,
        Err(error) => return Err(error),
        Ok(_) => {}
    }
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "TLS identity must be a private regular file",
        ));
    }
    let pem = fs::read(path)?;
    let cert = CertificateDer::from_pem_slice(&pem).map_err(io::Error::other)?;
    let key = PrivateKeyDer::from_pem_slice(&pem).map_err(io::Error::other)?;
    let digest = ring::digest::digest(&ring::digest::SHA256, cert.as_ref());
    let fingerprint = digest
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let mut config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .map_err(io::Error::other)?
    .with_no_client_auth()
    .with_single_cert(vec![cert], key)
    .map_err(io::Error::other)?;
    config.alpn_protocols = vec![b"http/1.1".to_vec()];
    Ok((RustlsConfig::from_config(Arc::new(config)), fingerprint))
}

fn generate(path: &Path) -> io::Result<()> {
    let CertifiedKey { cert, signing_key } =
        generate_simple_self_signed(vec!["ninjatap.local".into()]).map_err(io::Error::other)?;
    // Keep the certificate and key together so another startup can't read a half-written identity.
    let mut pending = tempfile::NamedTempFile::new_in(path.parent().unwrap())?;
    pending.write_all(cert.pem().as_bytes())?;
    pending.write_all(signing_key.serialize_pem().as_bytes())?;
    pending.as_file().sync_all()?;
    match pending.persist_noclobber(path) {
        Ok(_) => Ok(()),
        Err(error) if error.error.kind() == io::ErrorKind::AlreadyExists => Ok(()),
        Err(error) => Err(error.error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_the_same_private_identity_across_restarts() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("identity.pem");
        let (_, first) = load(&path).unwrap();
        let (_, second) = load(&path).unwrap();
        assert_eq!(first.len(), 64);
        assert_eq!(first, second);
        assert_eq!(
            fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }

    #[test]
    fn does_not_replace_a_damaged_identity() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("identity.pem");
        load(&path).unwrap();
        fs::write(&path, b"broken").unwrap();
        assert!(load(&path).is_err());
        assert_eq!(fs::read(&path).unwrap(), b"broken");
    }
}
