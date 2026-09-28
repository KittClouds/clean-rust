use std::path::Path;

use crate::FactoryError;

pub(crate) fn validate_relative_path(value: &str) -> Result<(), FactoryError> {
    if value.is_empty()
        || value.starts_with('/')
        || value.starts_with('\\')
        || value.contains('\\')
        || value.contains(':')
        || value.contains('\0')
    {
        return Err(FactoryError::Invalid(format!(
            "unsafe relative path: {value:?}"
        )));
    }
    for part in value.split('/') {
        if part.is_empty()
            || part == "."
            || part == ".."
            || part.ends_with('.')
            || part.ends_with(' ')
            || part
                .bytes()
                .any(|byte| byte < 0x20 || b"<>\"|?*".contains(&byte))
        {
            return Err(FactoryError::Invalid(format!(
                "unsafe path component in {value:?}"
            )));
        }
        let base = part.split('.').next().unwrap_or(part).to_ascii_uppercase();
        if matches!(base.as_str(), "CON" | "PRN" | "AUX" | "NUL")
            || (base.len() == 4
                && (base.starts_with("COM") || base.starts_with("LPT"))
                && base.as_bytes()[3].is_ascii_digit())
        {
            return Err(FactoryError::Invalid(format!(
                "reserved path component in {value:?}"
            )));
        }
    }
    if Path::new(value).is_absolute() {
        return Err(FactoryError::Invalid(format!(
            "absolute path rejected: {value:?}"
        )));
    }
    Ok(())
}

pub(crate) fn validate_identifier(value: &str, kind: &str) -> Result<(), FactoryError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        || value == "."
        || value == ".."
    {
        return Err(FactoryError::Invalid(format!("invalid {kind}: {value:?}")));
    }
    Ok(())
}
