use clap::{Arg, ColorChoice, Command};

pub fn configured_color() -> ColorChoice {
    Command::new("demo")
        .about("A compact command-line example")
        .arg(Arg::new("speed").long("speed").help("Execution speed"))
        // E012 candidate slot.
        .color(ColorChoice::Auto)
        .get_color()
}
