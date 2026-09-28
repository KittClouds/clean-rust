use clap::{Arg, ColorChoice, Command};

pub fn rendered_help() -> String {
    Command::new("demo")
        .about("A compact command-line example")
        .arg(Arg::new("speed").long("speed").help("Execution speed"))
        // E012 candidate slot.
        .color(ColorChoice::Auto)
        .render_help()
        .to_string()
}
