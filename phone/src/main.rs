fn main() {
    let mut bind = std::env::var("NINJATAP_BIND").unwrap_or_else(|_| "0.0.0.0:8787".into());
    let mut secret = std::env::var("NINJATAP_SECRET").unwrap_or_default();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--bind" => bind = args.next().unwrap_or_default(),
            "--secret" => secret = args.next().unwrap_or_default(),
            _ => {
                eprintln!("usage: ninjatap --bind 0.0.0.0:8787 --secret <token>");
                std::process::exit(2);
            }
        }
    }
    if secret.is_empty() || bind.is_empty() {
        eprintln!("NINJATAP_SECRET is required");
        std::process::exit(2);
    }
    let Some(identity) = std::env::var_os("NINJATAP_TLS_IDENTITY") else {
        eprintln!("NINJATAP_TLS_IDENTITY is required");
        std::process::exit(2);
    };
    ninjatap::input::install_exit_lift();
    if let Err(err) = ninjatap::http::serve(&bind, &secret, std::path::Path::new(&identity)) {
        eprintln!("{err}");
        std::process::exit(1);
    }
}
