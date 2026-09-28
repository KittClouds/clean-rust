use clap::{Arg, ArgAction, Command};

// E012 candidate slot: implementations differ in which spellings they support.
const FORMS: &[(&str, bool)] = &[("color", true)];

pub fn parse_color(argv: &[&str]) -> Option<bool> {
    let mut command = Command::new("demo");
    for (name, _) in FORMS {
        command = command.arg(Arg::new(*name).long(*name).action(ArgAction::SetTrue));
    }
    let matches = command.try_get_matches_from(argv.iter().copied()).ok()?;
    if FORMS.iter().any(|(name, enabled)| !enabled && matches.get_flag(*name)) {
        Some(false)
    } else if FORMS.iter().any(|(name, enabled)| *enabled && matches.get_flag(*name)) {
        Some(true)
    } else {
        None
    }
}
