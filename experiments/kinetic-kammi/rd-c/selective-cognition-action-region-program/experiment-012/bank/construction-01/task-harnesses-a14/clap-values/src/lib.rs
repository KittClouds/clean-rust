use clap::{Arg, Command};

pub fn accepts_speed(value: &str) -> bool {
    let command = Command::new("demo").arg(
        Arg::new("speed")
            .long("speed")
            // E012 candidate slot.
            .value_parser(["broken"]),
    );
    command
        .try_get_matches_from(["demo", "--speed", value])
        .is_ok()
}
