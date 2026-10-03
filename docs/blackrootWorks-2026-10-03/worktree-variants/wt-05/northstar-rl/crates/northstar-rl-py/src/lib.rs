use std::sync::Mutex;

use northstar_rl_core::{Digest, Environment, EnvironmentBatch};
use pyo3::{exceptions::PyRuntimeError, prelude::*};

type StepTuple = (
    Vec<f32>,
    f64,
    bool,
    bool,
    String,
    u64,
    u64,
    String,
    Option<String>,
);
type ResetTuple = (Vec<f32>, String, u64, String);

#[pyclass(name = "NativeEnvironment")]
struct PyNorthstarEnvironment {
    inner: Mutex<Environment>,
}

#[pyclass(name = "NativeEnvironmentBatch")]
struct PyNorthstarEnvironmentBatch {
    inner: Mutex<EnvironmentBatch>,
}

#[pymethods]
impl PyNorthstarEnvironment {
    #[staticmethod]
    fn open(config_path: &str) -> PyResult<Self> {
        Ok(Self {
            inner: Mutex::new(Environment::open(config_path).map_err(native_error)?),
        })
    }

    #[pyo3(signature = (episode_id=None, seed=0))]
    fn reset_episode(
        &self,
        episode_id: Option<&str>,
        seed: u64,
    ) -> PyResult<(Vec<f32>, String, u64, String)> {
        let episode_id = episode_id
            .map(str::parse::<Digest>)
            .transpose()
            .map_err(native_error)?;
        let output = self
            .lock()?
            .reset_episode(episode_id, seed)
            .map_err(native_error)?;
        let ancestry = serde_json::to_string(&output.seed_ancestry).map_err(native_error)?;
        Ok((
            output.observation,
            output.episode_id.to_string(),
            output.source_row_id,
            ancestry,
        ))
    }

    fn step(&self, action: f32) -> PyResult<StepTuple> {
        let output = self.lock()?.step(action).map_err(native_error)?;
        let reason = output
            .terminal_reason
            .map(serde_json::to_value)
            .transpose()
            .map_err(native_error)?
            .and_then(|value| value.as_str().map(str::to_owned));
        Ok((
            output.observation,
            output.reward,
            output.terminated,
            output.truncated,
            output.episode_id.to_string(),
            output.step_id,
            output.source_row_id,
            output.execution_receipt_id.to_string(),
            reason,
        ))
    }

    fn current_observation(&self) -> PyResult<Vec<f32>> {
        self.lock()?.current_observation().map_err(native_error)
    }

    fn diagnostics(&self) -> PyResult<String> {
        let environment = self.lock()?;
        serde_json::to_string(&serde_json::json!({
            "render": environment.render_text(),
            "account": environment.account(),
            "trajectory_root": environment.trajectory_root().map_err(native_error)?.to_string(),
            "step_count": environment.steps().len(),
        }))
        .map_err(native_error)
    }

    fn render(&self) -> PyResult<String> {
        Ok(self.lock()?.render_text())
    }

    fn close_environment(&self) -> PyResult<()> {
        self.lock()?.close();
        Ok(())
    }

    fn observation_shape(&self) -> PyResult<Vec<usize>> {
        Ok(self
            .lock()?
            .config()
            .observation_spec
            .output_shape
            .iter()
            .map(|&dimension| dimension as usize)
            .collect())
    }

    fn environment_id(&self) -> PyResult<String> {
        Ok(self
            .lock()?
            .config()
            .environment_spec
            .environment_id
            .to_string())
    }
}

#[pymethods]
impl PyNorthstarEnvironmentBatch {
    #[staticmethod]
    fn open(config_path: &str, lane_count: usize) -> PyResult<Self> {
        Ok(Self {
            inner: Mutex::new(
                EnvironmentBatch::open(config_path, lane_count).map_err(native_error)?,
            ),
        })
    }

    fn reset_many(&self, seeds: Vec<u64>) -> PyResult<Vec<ResetTuple>> {
        let output = self.lock()?.reset_many(&[], &seeds).map_err(native_error)?;
        output
            .into_iter()
            .map(|reset| {
                Ok((
                    reset.observation,
                    reset.episode_id.to_string(),
                    reset.source_row_id,
                    serde_json::to_string(&reset.seed_ancestry).map_err(native_error)?,
                ))
            })
            .collect()
    }

    fn step_many(&self, actions: Vec<f32>) -> PyResult<Vec<StepTuple>> {
        self.lock()?
            .step_many(&actions)
            .map_err(native_error)?
            .into_iter()
            .map(|output| {
                let reason = output
                    .terminal_reason
                    .map(serde_json::to_value)
                    .transpose()
                    .map_err(native_error)?
                    .and_then(|value| value.as_str().map(str::to_owned));
                Ok((
                    output.observation,
                    output.reward,
                    output.terminated,
                    output.truncated,
                    output.episode_id.to_string(),
                    output.step_id,
                    output.source_row_id,
                    output.execution_receipt_id.to_string(),
                    reason,
                ))
            })
            .collect()
    }

    fn lane_count(&self) -> PyResult<usize> {
        Ok(self.lock()?.len())
    }
}

impl PyNorthstarEnvironment {
    fn lock(&self) -> PyResult<std::sync::MutexGuard<'_, Environment>> {
        self.inner
            .lock()
            .map_err(|_| PyRuntimeError::new_err("native environment lock poisoned"))
    }
}

impl PyNorthstarEnvironmentBatch {
    fn lock(&self) -> PyResult<std::sync::MutexGuard<'_, EnvironmentBatch>> {
        self.inner
            .lock()
            .map_err(|_| PyRuntimeError::new_err("native environment batch lock poisoned"))
    }
}

#[pyfunction]
fn open_environment(config_path: &str) -> PyResult<PyNorthstarEnvironment> {
    PyNorthstarEnvironment::open(config_path)
}

#[pyfunction]
fn open_environment_batch(
    config_path: &str,
    lane_count: usize,
) -> PyResult<PyNorthstarEnvironmentBatch> {
    PyNorthstarEnvironmentBatch::open(config_path, lane_count)
}

#[pymodule]
fn _northstar_rl(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyNorthstarEnvironment>()?;
    module.add_class::<PyNorthstarEnvironmentBatch>()?;
    module.add_function(wrap_pyfunction!(open_environment, module)?)?;
    module.add_function(wrap_pyfunction!(open_environment_batch, module)?)?;
    module.add("ABI_CONTRACT", "NORTHSTAR_PYO3_ABI_V2")?;
    Ok(())
}

fn native_error(error: impl std::fmt::Display) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}
