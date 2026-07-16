fn main() {
    let target = std::env::var("TARGET").expect("Cargo TARGET");
    println!("cargo:rustc-env=PHOENIX_BUILD_TARGET={target}");
}
