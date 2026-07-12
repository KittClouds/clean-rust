fn main() {
    println!("cargo:rerun-if-changed=../.git/HEAD");
    if let Some(git_ref) = git_output(&["symbolic-ref", "-q", "HEAD"]) {
        println!("cargo:rerun-if-changed=../.git/{git_ref}");
    }
    let git_sha =
        git_output(&["rev-parse", "--verify", "HEAD"]).unwrap_or_else(|| "unknown".to_owned());
    println!("cargo:rustc-env=PHOENIX_BUILD_GIT_SHA={git_sha}");
    tauri_build::build()
}

fn git_output(args: &[&str]) -> Option<String> {
    std::process::Command::new("git")
        .args(args)
        .current_dir("..")
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}
