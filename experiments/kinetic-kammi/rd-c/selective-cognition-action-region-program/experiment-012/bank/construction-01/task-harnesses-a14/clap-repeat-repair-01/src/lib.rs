use clap::{Arg, ArgAction, Command};

pub fn parse_tag_values(argv: &[&str]) -> Vec<String> {
    // E012 candidate slot.
    let command = Command::new("demo")
        .arg(Arg::new("tag").long("tag").action(ArgAction::Set));
    let matches = command
        .try_get_matches_from(argv.iter().copied())
        .expect("valid task arguments");
    matches
        .get_many::<String>("tag")
        .map(|values| values.cloned().collect())
        .unwrap_or_default()
}
