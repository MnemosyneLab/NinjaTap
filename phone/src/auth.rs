//! Bearer token check for requests from the computer.

pub fn bearer_matches(header: Option<&str>, secret: &str) -> bool {
    if secret.is_empty() {
        return false;
    }
    match header {
        Some(value) => value
            .strip_prefix("Bearer ")
            .is_some_and(|token| token == secret),
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_the_exact_bearer_token() {
        assert!(bearer_matches(Some("Bearer secret"), "secret"));
        assert!(!bearer_matches(Some("Bearer other"), "secret"));
        assert!(!bearer_matches(Some("secret"), "secret"));
        assert!(!bearer_matches(None, "secret"));
        assert!(!bearer_matches(Some("Bearer secret"), ""));
    }
}
