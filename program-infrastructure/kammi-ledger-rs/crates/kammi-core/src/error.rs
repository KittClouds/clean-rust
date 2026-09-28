use kammi_jcs::JcsError;
use kammi_store::StoreError;

/// Errors carry the Python exception kind they replace, so the HTTP layer can reproduce the
/// exact status code and `detail` text of the Python service.
#[derive(Debug, thiserror::Error)]
pub enum LedgerError {
    /// Python `ValueError(message)`: detail is the message.
    #[error("{0}")]
    Value(String),
    /// Python `KeyError(key)`: detail is the quoted key, e.g. `'run_id'`.
    #[error("'{0}'")]
    Key(String),
    /// Python `TypeError`.
    #[error("{0}")]
    Type(String),
    /// Authority storage failed; never a client mistake.
    #[error(transparent)]
    Store(#[from] StoreError),
    /// A derived service the operation needs (the memory projection) is down; authority is
    /// unaffected. HTTP maps this to 503.
    #[error("{0}")]
    Unavailable(String),
    #[error("I/O error on {path}: {source}")]
    Io {
        path: std::path::PathBuf,
        #[source]
        source: std::io::Error,
    },
}

impl LedgerError {
    /// True for the errors Python routes map to a 4xx response (ValueError, KeyError,
    /// TypeError). Everything else is an internal failure.
    pub fn is_client(&self) -> bool {
        matches!(
            self,
            LedgerError::Value(_) | LedgerError::Key(_) | LedgerError::Type(_)
        )
    }

    /// The `detail` string Python would put in the HTTP error body.
    pub fn detail(&self) -> String {
        self.to_string()
    }
}

impl From<JcsError> for LedgerError {
    fn from(error: JcsError) -> Self {
        // identity.strict_json / canonical raise ValueError with these messages.
        LedgerError::Value(error.to_string())
    }
}

pub type Result<T> = std::result::Result<T, LedgerError>;

/// Shorthand for `Err(LedgerError::Value(..))`.
pub fn value_error<T>(message: impl Into<String>) -> Result<T> {
    Err(LedgerError::Value(message.into()))
}

pub fn io_error(path: impl Into<std::path::PathBuf>) -> impl FnOnce(std::io::Error) -> LedgerError {
    let path = path.into();
    move |source| LedgerError::Io { path, source }
}
