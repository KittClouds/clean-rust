use std::fmt;

use northstar_rl_core::{Digest, identity};
use zeroize::Zeroize;

use crate::{
    BrokerAccountSnapshot, BrokerInstrument, BrokerObservationTape, BrokerPositionProjection,
    BrokerQuoteObservation, ConnectionDiagnostic, ConnectionState, ExecutionRealityRow, Result,
};

pub const DEFAULT_CREDENTIAL_TARGET: &str = "Northstar/TradeLocker/live";

/// Northstar-shaped, read-only boundary. There is deliberately no command method.
pub trait TradeLockerObserver {
    fn instruments(&mut self) -> Result<Vec<BrokerInstrument>>;
    fn quote(&mut self, instrument_id: u32) -> Result<BrokerQuoteObservation>;
    fn account_snapshot(&mut self) -> Result<BrokerAccountSnapshot>;
    fn positions(&mut self) -> Result<Vec<BrokerPositionProjection>>;
    fn execution_history(&mut self, start_ns: i64, end_ns: i64)
    -> Result<Vec<ExecutionRealityRow>>;
    fn historical_prices(
        &mut self,
        instrument_id: u32,
        start_ns: i64,
        end_ns: i64,
    ) -> Result<Vec<BrokerQuoteObservation>>;
    fn connection_status(&self) -> ConnectionDiagnostic;
}

pub struct CapturedTradeLockerObserver {
    tape: BrokerObservationTape,
    cursor: usize,
    instruments: Vec<BrokerInstrument>,
    account: BrokerAccountSnapshot,
    positions: Vec<BrokerPositionProjection>,
}

impl CapturedTradeLockerObserver {
    pub fn new(
        tape: BrokerObservationTape,
        instruments: Vec<BrokerInstrument>,
        account: BrokerAccountSnapshot,
        positions: Vec<BrokerPositionProjection>,
    ) -> Self {
        Self {
            tape,
            cursor: 0,
            instruments,
            account,
            positions,
        }
    }
}

impl TradeLockerObserver for CapturedTradeLockerObserver {
    fn instruments(&mut self) -> Result<Vec<BrokerInstrument>> {
        Ok(self.instruments.clone())
    }

    fn quote(&mut self, instrument_id: u32) -> Result<BrokerQuoteObservation> {
        let matching = self
            .tape
            .rows
            .iter()
            .filter(|row| row.instrument_id == instrument_id)
            .collect::<Vec<_>>();
        if matching.is_empty() {
            return Err(crate::Error::Contract(
                "capture has no matching instrument".into(),
            ));
        }
        let row = matching[self.cursor.min(matching.len() - 1)].clone();
        self.cursor = (self.cursor + 1).min(matching.len());
        Ok(row)
    }

    fn account_snapshot(&mut self) -> Result<BrokerAccountSnapshot> {
        Ok(self.account.clone())
    }
    fn positions(&mut self) -> Result<Vec<BrokerPositionProjection>> {
        Ok(self.positions.clone())
    }
    fn execution_history(
        &mut self,
        _start_ns: i64,
        _end_ns: i64,
    ) -> Result<Vec<ExecutionRealityRow>> {
        Ok(Vec::new())
    }
    fn historical_prices(
        &mut self,
        instrument_id: u32,
        start_ns: i64,
        end_ns: i64,
    ) -> Result<Vec<BrokerQuoteObservation>> {
        Ok(self
            .tape
            .rows
            .iter()
            .filter(|row| {
                row.instrument_id == instrument_id
                    && row.event_time_ns >= start_ns
                    && row.event_time_ns <= end_ns
            })
            .cloned()
            .collect())
    }
    fn connection_status(&self) -> ConnectionDiagnostic {
        ConnectionDiagnostic {
            provider: "TRADELOCKER".into(),
            credential_provider: "SEALED_CAPTURE".into(),
            credential_alias: "NONE_OFFLINE".into(),
            credential_resolved: true,
            authenticated_account_id_hash: Some(self.tape.account_id_hash),
            connection_environment: "OFFLINE_REPLAY".into(),
            connection_state: ConnectionState::CapturedReplay,
            detail_code: "SEALED_CAPTURE_VALID".into(),
        }
    }
}

pub struct ProtectedSecret {
    email: String,
    password: String,
}

impl ProtectedSecret {
    pub fn email(&self) -> &str {
        &self.email
    }
    pub fn password(&self) -> &str {
        &self.password
    }
}

impl fmt::Debug for ProtectedSecret {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("ProtectedSecret(<redacted>)")
    }
}

impl Drop for ProtectedSecret {
    fn drop(&mut self) {
        self.email.zeroize();
        self.password.zeroize();
    }
}

pub fn credential_alias() -> String {
    std::env::var("NORTHSTAR_TRADELOCKER_CREDENTIAL_TARGET")
        .unwrap_or_else(|_| DEFAULT_CREDENTIAL_TARGET.into())
}

pub fn credential_probe(environment: &str) -> ConnectionDiagnostic {
    let alias = credential_alias();
    match read_generic_credential(&alias) {
        Ok(secret) => {
            let provider_identity = Digest::hash(
                b"northstar-credential-principal-v1",
                secret.email().as_bytes(),
            );
            drop(secret);
            ConnectionDiagnostic {
                provider: "TRADELOCKER".into(),
                credential_provider: "WINDOWS_GENERIC_CREDENTIAL".into(),
                credential_alias: alias,
                credential_resolved: true,
                authenticated_account_id_hash: None,
                connection_environment: environment.into(),
                connection_state: ConnectionState::Unavailable,
                detail_code: format!("CREDENTIAL_RESOLVED_PRINCIPAL_HASH_{provider_identity}"),
            }
        }
        Err(error) => ConnectionDiagnostic {
            provider: "TRADELOCKER".into(),
            credential_provider: "WINDOWS_GENERIC_CREDENTIAL".into(),
            credential_alias: alias,
            credential_resolved: false,
            authenticated_account_id_hash: None,
            connection_environment: environment.into(),
            connection_state: ConnectionState::Unavailable,
            detail_code: format!(
                "CREDENTIAL_UNAVAILABLE_{}",
                sanitize_code(&error.to_string())
            ),
        },
    }
}

fn sanitize_code(value: &str) -> String {
    value
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .take(96)
        .collect()
}

#[cfg(windows)]
pub fn read_generic_credential(target: &str) -> Result<ProtectedSecret> {
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::Security::Credentials::{
        CRED_TYPE_GENERIC, CREDENTIALW, CredFree, CredReadW,
    };
    let mut target_wide = target.encode_utf16().collect::<Vec<_>>();
    target_wide.push(0);
    let mut pointer: *mut CREDENTIALW = std::ptr::null_mut();
    // SAFETY: target is NUL terminated and pointer is a valid out parameter.
    let ok = unsafe { CredReadW(target_wide.as_ptr(), CRED_TYPE_GENERIC, 0, &mut pointer) };
    if ok == 0 || pointer.is_null() {
        // SAFETY: GetLastError has no preconditions.
        return Err(crate::Error::Credential(format!(
            "windows_error_{}",
            unsafe { GetLastError() }
        )));
    }
    // SAFETY: CredReadW owns a valid allocation until CredFree.
    let credential = unsafe { &*pointer };
    let email = unsafe { read_wide(credential.UserName) };
    let blob_len = credential.CredentialBlobSize as usize;
    let mut blob = if blob_len == 0 || credential.CredentialBlob.is_null() {
        Vec::new()
    } else {
        // SAFETY: blob pointer spans CredentialBlobSize bytes.
        unsafe { std::slice::from_raw_parts(credential.CredentialBlob, blob_len) }.to_vec()
    };
    // SAFETY: pointer came from CredReadW.
    unsafe { CredFree(pointer.cast()) };
    let email = email?;
    let mut password = decode_blob(&blob)?;
    blob.zeroize();
    if email.trim().is_empty() || password.len() < 8 || password.chars().any(char::is_control) {
        password.zeroize();
        return Err(crate::Error::Credential("credential_invalid".into()));
    }
    Ok(ProtectedSecret { email, password })
}

#[cfg(windows)]
unsafe fn read_wide(pointer: *const u16) -> Result<String> {
    if pointer.is_null() {
        return Err(crate::Error::Credential("username_missing".into()));
    }
    let mut len = 0usize;
    while len < 4096 {
        // SAFETY: Windows credential strings are NUL terminated within the allocation.
        if unsafe { *pointer.add(len) } == 0 {
            // SAFETY: scan above established initialized range.
            return String::from_utf16(unsafe { std::slice::from_raw_parts(pointer, len) })
                .map_err(|_| crate::Error::Credential("username_encoding".into()));
        }
        len += 1;
    }
    Err(crate::Error::Credential("username_unterminated".into()))
}

fn decode_blob(bytes: &[u8]) -> Result<String> {
    if bytes.is_empty() {
        return Err(crate::Error::Credential("password_empty".into()));
    }
    let utf16 = bytes.len().is_multiple_of(2)
        && bytes.chunks_exact(2).filter(|pair| pair[1] == 0).count() * 4 >= bytes.len();
    if utf16 {
        let units = bytes
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .take_while(|u| *u != 0)
            .collect::<Vec<_>>();
        String::from_utf16(&units).map_err(|_| crate::Error::Credential("password_encoding".into()))
    } else {
        std::str::from_utf8(bytes)
            .map(str::to_owned)
            .map_err(|_| crate::Error::Credential("password_encoding".into()))
    }
}

#[cfg(not(windows))]
pub fn read_generic_credential(_target: &str) -> Result<ProtectedSecret> {
    Err(crate::Error::Credential(
        "windows_credential_provider_required".into(),
    ))
}

pub fn stable_snapshot_hash<T: serde::Serialize>(domain: &[u8], value: &T) -> Result<Digest> {
    Ok(identity(domain, value)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secret_debug_is_redacted() {
        let secret = ProtectedSecret {
            email: "person@example.test".into(),
            password: "not-a-real-password".into(),
        };
        let text = format!("{secret:?}");
        assert_eq!(text, "ProtectedSecret(<redacted>)");
        assert!(!text.contains("person"));
    }

    #[test]
    fn utf8_and_utf16_secret_blobs_decode() {
        assert_eq!(
            decode_blob(b"sanitized-password").unwrap(),
            "sanitized-password"
        );
        let bytes = "sanitized-password"
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect::<Vec<_>>();
        assert_eq!(decode_blob(&bytes).unwrap(), "sanitized-password");
    }
}
