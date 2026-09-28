//! One resident GLiNER2.5 worker, bounded replies and no fallback after failure.
use anyhow::{bail, ensure, Context, Result};
use phoenix_analysis_contract::AnalysisModelIdentity;
use phoenix_dynamic_ner::{
    DiscoveredSpan, DynamicNerModel, LabelPack, LocalMentionId, MentionVote, ModelNerWindow,
    NerModelError, VerificationCase,
};
use phoenix_gliner25_contract::*;
use std::{
    fs::File,
    io::BufReader,
    path::Path,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        mpsc::{self, Receiver},
        Mutex,
    },
    time::Duration,
};

pub struct Backend {
    connection: Mutex<Connection>,
}
struct Connection {
    child: Child,
    input: ChildStdin,
    output: Receiver<Result<Response, String>>,
    sequence: u64,
    failed: bool,
    _pins: Vec<File>,
    #[cfg(windows)]
    _job: Job,
}
impl Backend {
    pub fn load(root: &Path) -> Result<(Self, AnalysisModelIdentity)> {
        let config_path = root.join("gliner25.json");
        let bundle = Bundle::read(&config_path)?;
        let pins = vec![pin(&bundle.worker)?, pin(&bundle.ort)?];
        let digest = bundle.digest()?;
        let mut command = Command::new(&bundle.worker.path);
        command
            .arg("serve")
            .arg(&config_path)
            .env("ORT_DYLIB_PATH", &bundle.ort.path)
            .env("GLINER2_DEVICE", "cpu")
            .env("GLINER2_PRECISION", "fp32")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command.spawn().context("launch GLiNER2.5 worker")?;
        #[cfg(windows)]
        let job = match Job::attach(&child) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        let input = child.stdin.take().context("GLiNER stdin unavailable")?;
        let stdout = child.stdout.take().context("GLiNER stdout unavailable")?;
        let (tx, rx) = mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut input = BufReader::new(stdout);
            loop {
                let frame = read_frame(&mut input).map_err(|e| format!("{e:#}"));
                let failed = frame.is_err();
                if tx.send(frame).is_err() || failed {
                    break;
                }
            }
        });
        let mut connection = Connection {
            child,
            input,
            output: rx,
            sequence: 0,
            failed: false,
            _pins: pins,
            #[cfg(windows)]
            _job: job,
        };
        match connection.receive(Duration::from_secs(180))? {
            Response::Ready {
                contract,
                bundle,
                pid,
            } if contract == CONTRACT && bundle == digest && pid == connection.child.id() => {}
            _ => bail!("GLiNER2.5 worker identity handshake mismatch"),
        }
        let identity = AnalysisModelIdentity {
            model_id: format!("phoenix-dynamic-ner+{}", bundle.model_revision),
            artifact_hash: digest,
            config_hash: *blake3::hash(POLICY.as_bytes()).as_bytes(),
            runtime_id: format!(
                "gliner25-rs/a639bad;ort-rc.13;cpu;threads={};worker={}",
                bundle.threads,
                blake3::Hash::from(bundle.worker.hash)
            ),
        };
        Ok((
            Self {
                connection: Mutex::new(connection),
            },
            identity,
        ))
    }
    fn infer(&self, text: &str, labels: Vec<String>) -> Result<Vec<DiscoveredSpan>> {
        if labels.is_empty() {
            return Ok(Vec::new());
        }
        let mut c = self
            .connection
            .lock()
            .map_err(|_| anyhow::anyhow!("GLiNER worker lock poisoned"))?;
        ensure!(
            !c.failed,
            "GLiNER worker failed; reconnect runtime before retry"
        );
        c.sequence = c.sequence.checked_add(1).context("sequence exhausted")?;
        let request = Request {
            sequence: c.sequence,
            text: text.into(),
            labels,
        };
        request.validate()?;
        let outcome = (|| {
            write_frame(&mut c.input, &request)?;
            match c.receive(Duration::from_secs(120))? {
                Response::Completed {
                    sequence,
                    text_hash,
                    spans,
                    inference_micros,
                } => {
                    ensure!(
                        sequence == request.sequence
                            && text_hash == *blake3::hash(text.as_bytes()).as_bytes(),
                        "stale GLiNER reply"
                    );
                    validate_spans(text, &request.labels, &spans)?;
                    eprintln!("PHOENIX_GLINER25_WINDOW sequence={sequence} bytes={} spans={} inference_micros={inference_micros}",text.len(),spans.len());
                    let mut by_key = std::collections::BTreeMap::new();
                    for span in spans {
                        crate::ner::insert_model_prediction(
                            &mut by_key,
                            phoenix_rel_post::GlinerBiPrediction {
                                text: span.text,
                                label: span.label,
                                span_start: span.start as usize,
                                span_end: span.end as usize,
                                score: span.score,
                            },
                        );
                    }
                    Ok(by_key.into_values().collect())
                }
                Response::Failed { sequence, message } => {
                    bail!("GLiNER request {sequence}: {message}")
                }
                _ => bail!("unexpected GLiNER worker response"),
            }
        })();
        if outcome.is_err() {
            c.failed = true;
            let _ = c.child.kill();
            let _ = c.child.wait();
        }
        outcome
    }
}
impl Connection {
    fn receive(&mut self, timeout: Duration) -> Result<Response> {
        self.output
            .recv_timeout(timeout)
            .context("GLiNER worker timeout or EOF")?
            .map_err(anyhow::Error::msg)
    }
}
impl Drop for Connection {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
impl DynamicNerModel for Backend {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        labels: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError> {
        self.infer(window.text, crate::ner::model_labels(labels))
            .map_err(|e| NerModelError::Inference(format!("{e:#}")))
    }
    fn verify(
        &self,
        _: &[VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError> {
        Ok(Vec::new())
    }
}

#[cfg(windows)]
struct Job(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
unsafe impl Send for Job {} // Owned handle; accessed only behind the connection mutex.
#[cfg(windows)]
impl Job {
    fn attach(child: &Child) -> Result<Self> {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::System::JobObjects::*;
        unsafe {
            let job = Self(CreateJobObjectW(std::ptr::null(), std::ptr::null()));
            ensure!(
                !job.0.is_null(),
                "create worker job: {}",
                std::io::Error::last_os_error()
            );
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            ensure!(
                SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                    std::mem::size_of_val(&info) as u32
                ) != 0,
                "set worker job: {}",
                std::io::Error::last_os_error()
            );
            ensure!(
                AssignProcessToJobObject(job.0, child.as_raw_handle()) != 0,
                "assign worker job: {}",
                std::io::Error::last_os_error()
            );
            Ok(job)
        }
    }
}
#[cfg(windows)]
impl Drop for Job {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.0);
            }
        }
    }
}
