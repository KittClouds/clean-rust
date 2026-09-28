use half::f16;
use ort::memory::{AllocationDevice, AllocatorType, MemoryInfo, MemoryType};
use ort::session::{Session, SessionInputValue};
use ort::value::{DynValue, TensorRefMut};
use phoenix_rel_post::{
    evaluate_packet_output, missing_required_keys, parse_advisor_output, AdvisorPacketEvaluation,
    AdvisorProbeTask,
};
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use tokenizers::Tokenizer;

const SYSTEM_PROMPT: &str = "You are a tiny late-stage Phoenix graph aide. Return one compact JSON object only. Do not use markdown fences. Fill values from evidence; never copy placeholder text. The first character of your answer must be { and the final character must be }. Never write prose before or after the JSON object. Do not assert graph truth, mutate graph truth, or invent missing evidence. Use review/deferred language when the evidence is weak.";

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RunResult {
    pub prompt_token_count: usize,
    pub generated_token_count: usize,
    pub text: String,
    pub parsed_json: Option<Value>,
    pub json_error: Option<String>,
    pub schema_error: Option<String>,
    pub first_ms: f64,
    pub avg_decode_ms: f64,
    pub cache: CacheStats,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CacheStats {
    pub kv_bytes: usize,
    pub total_bytes: usize,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskResult {
    pub task: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub packet_kind: Option<String>,
    pub prompt: String,
    pub raw: RunResult,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evaluation: Option<AdvisorPacketEvaluation>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProbeReport {
    pub model_root: String,
    pub variant: String,
    pub report_path: String,
    pub timestamp_ms: i64,
    pub tasks: Vec<TaskResult>,
}

#[derive(Clone, Debug)]
enum CacheTensor {
    F32x3([usize; 3], Vec<f32>),
    F32x4([usize; 4], Vec<f32>),
    F16x3([usize; 3], Vec<f16>),
    F16x4([usize; 4], Vec<f16>),
}

impl CacheTensor {
    fn kv_bytes(&self) -> usize {
        match self {
            Self::F32x4(_, values) => std::mem::size_of_val(values.as_slice()),
            Self::F16x4(_, values) => std::mem::size_of_val(values.as_slice()),
            _ => 0,
        }
    }

    fn total_bytes(&self) -> usize {
        match self {
            Self::F32x3(_, values) | Self::F32x4(_, values) => {
                std::mem::size_of_val(values.as_slice())
            }
            Self::F16x3(_, values) | Self::F16x4(_, values) => {
                std::mem::size_of_val(values.as_slice())
            }
        }
    }
}

struct StepOutputs {
    logits: DynValue,
    cache_outputs: Vec<(String, DynValue)>,
}

#[derive(Default)]
pub struct ProbeScratch {
    input_ids: Vec<i64>,
    attention_mask: Vec<i64>,
    position_ids: Vec<i64>,
    logits_keep: Vec<i64>,
}

impl ProbeScratch {
    fn prepare(&mut self, ids: &[i64], total_length: usize) {
        self.input_ids.clear();
        self.input_ids.extend_from_slice(ids);
        self.attention_mask.resize(total_length, 1);
        self.position_ids.resize(ids.len(), 0);
        let start = total_length.saturating_sub(ids.len()) as i64;
        for (index, slot) in self.position_ids.iter_mut().enumerate() {
            *slot = start + index as i64;
        }
        if self.logits_keep.is_empty() {
            self.logits_keep.push(1);
        }
    }
}

pub fn run_task(
    session: &Session,
    tokenizer: &Tokenizer,
    task: &AdvisorProbeTask,
    max_new_tokens: usize,
    memory_info: &MemoryInfo,
    scratch: &mut ProbeScratch,
) -> Result<RunResult, String> {
    let prompt = build_prompt(task);
    let encoding = tokenizer
        .encode(prompt, true)
        .map_err(|error| format!("encode prompt for {}: {error}", task.name))?;
    let prompt_ids = encoding
        .get_ids()
        .iter()
        .map(|&value| i64::from(value))
        .collect::<Vec<_>>();
    let eos_id = tokenizer
        .token_to_id("<|im_end|>")
        .map(i64::from)
        .ok_or_else(|| "missing <|im_end|> token".to_owned())?;
    let mut cache = initialize_cache(session);
    let mut tokens = Vec::with_capacity(max_new_tokens.max(1));
    let mut decode_ms = Vec::with_capacity(max_new_tokens.saturating_sub(1));

    let first_start = std::time::Instant::now();
    let first_outputs = run_step(
        session,
        &prompt_ids,
        prompt_ids.len(),
        &mut cache,
        memory_info,
        scratch,
    )?;
    let first_ms = first_start.elapsed().as_secs_f64() * 1000.0;
    let mut token = argmax(&extract_last_logits(&first_outputs.logits)?)
        .ok_or_else(|| "empty logits".to_owned())?;
    tokens.push(token);
    update_cache(&mut cache, &first_outputs.cache_outputs)?;
    let mut total_length = prompt_ids.len() + 1;

    for _ in 1..max_new_tokens.max(1) {
        if token == eos_id {
            break;
        }
        let start = std::time::Instant::now();
        let outputs = run_step(
            session,
            &[token],
            total_length,
            &mut cache,
            memory_info,
            scratch,
        )?;
        decode_ms.push(start.elapsed().as_secs_f64() * 1000.0);
        token = argmax(&extract_last_logits(&outputs.logits)?)
            .ok_or_else(|| "empty logits".to_owned())?;
        tokens.push(token);
        update_cache(&mut cache, &outputs.cache_outputs)?;
        total_length += 1;
        let text = clean_text(tokenizer, &task.prefill, &tokens)?;
        let (parsed, json_error) = parse_advisor_output(&text);
        if json_error.is_none()
            && missing_required_keys(parsed.as_ref(), &task.required_keys).is_none()
        {
            break;
        }
    }

    let text = clean_text(tokenizer, &task.prefill, &tokens)?;
    let (parsed_json, json_error) = parse_advisor_output(&text);
    let schema_error = missing_required_keys(parsed_json.as_ref(), &task.required_keys);
    Ok(RunResult {
        prompt_token_count: prompt_ids.len(),
        generated_token_count: tokens.len(),
        text,
        schema_error,
        parsed_json,
        json_error,
        first_ms,
        avg_decode_ms: average(&decode_ms),
        cache: cache_stats(&cache),
    })
}

pub fn build_task_result(task: &AdvisorProbeTask, raw: RunResult) -> TaskResult {
    let evaluation = evaluate_packet_output(task, raw.parsed_json.as_ref());
    TaskResult {
        task: task.name.clone(),
        packet_kind: task.packet_kind.clone(),
        prompt: task.prompt.clone(),
        raw,
        evaluation,
    }
}

fn build_prompt(task: &AdvisorProbeTask) -> String {
    format!(
        "<|startoftext|><|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n\
         <|im_start|>user\n{}\nOutput contract: return exactly one JSON object with every \
         requested key. Do not close the object until all requested keys are present. No \
         markdown, no prose, no schema placeholders. Continue the assistant JSON prefix.\
         <|im_end|>\n<|im_start|>assistant\n{}",
        task.prompt, task.prefill
    )
}

fn run_step(
    session: &Session,
    ids: &[i64],
    total_length: usize,
    cache: &mut BTreeMap<String, CacheTensor>,
    memory_info: &MemoryInfo,
    scratch: &mut ProbeScratch,
) -> Result<StepOutputs, String> {
    scratch.prepare(ids, total_length);
    let input_shape = [1, ids.len() as i64];
    let attention_shape = [1, total_length as i64];
    let input_ids = tensor_ref_from_i64_buffer(
        memory_info,
        &mut scratch.input_ids,
        Vec::from(input_shape),
        "input_ids",
    )?;
    let attention_mask = tensor_ref_from_i64_buffer(
        memory_info,
        &mut scratch.attention_mask,
        Vec::from(attention_shape),
        "attention_mask",
    )?;
    let position_ids = tensor_ref_from_i64_buffer(
        memory_info,
        &mut scratch.position_ids,
        Vec::from(input_shape),
        "position_ids",
    )?;
    let logits_keep = tensor_ref_from_i64_buffer(
        memory_info,
        &mut scratch.logits_keep,
        Vec::new(),
        "num_logits_to_keep",
    )?;
    let mut feeds = Vec::with_capacity(session.inputs.len());
    for input in &session.inputs {
        let name = input.name.as_str();
        let value = match name {
            "input_ids" => SessionInputValue::from(input_ids.view()),
            "attention_mask" => SessionInputValue::from(attention_mask.view()),
            "position_ids" => SessionInputValue::from(position_ids.view()),
            "num_logits_to_keep" => SessionInputValue::from(logits_keep.view()),
            _ => continue,
        };
        feeds.push((name, value));
    }
    for (name, value) in cache.iter_mut() {
        feeds.push((name.as_str(), build_cache_input(name, value, memory_info)?));
    }

    let outputs = session
        .run(feeds)
        .map_err(|error| format!("session run: {error}"))?;
    let mut logits = None;
    let cache_outputs = outputs
        .into_iter()
        .filter_map(|(name, value)| {
            if name == "logits" {
                logits = Some(value);
                None
            } else {
                Some((name.to_owned(), value))
            }
        })
        .collect::<Vec<_>>();
    Ok(StepOutputs {
        logits: logits.ok_or_else(|| "missing logits output".to_owned())?,
        cache_outputs,
    })
}

fn build_cache_input<'a>(
    name: &str,
    value: &'a mut CacheTensor,
    memory_info: &MemoryInfo,
) -> Result<SessionInputValue<'a>, String> {
    match value {
        CacheTensor::F32x3(shape, values) => {
            Ok(SessionInputValue::from(tensor_ref_from_f32_cache(
                memory_info,
                values,
                shape.iter().map(|&dim| dim as i64).collect(),
                name,
            )?))
        }
        CacheTensor::F32x4(shape, values) => {
            Ok(SessionInputValue::from(tensor_ref_from_f32_cache(
                memory_info,
                values,
                shape.iter().map(|&dim| dim as i64).collect(),
                name,
            )?))
        }
        CacheTensor::F16x3(shape, values) => {
            Ok(SessionInputValue::from(tensor_ref_from_f16_cache(
                memory_info,
                values,
                shape.iter().map(|&dim| dim as i64).collect(),
                name,
            )?))
        }
        CacheTensor::F16x4(shape, values) => {
            Ok(SessionInputValue::from(tensor_ref_from_f16_cache(
                memory_info,
                values,
                shape.iter().map(|&dim| dim as i64).collect(),
                name,
            )?))
        }
    }
}

fn initialize_cache(session: &Session) -> BTreeMap<String, CacheTensor> {
    let mut cache = BTreeMap::new();
    for input in &session.inputs {
        if input.name.starts_with("past_conv") {
            cache.insert(
                input.name.clone(),
                CacheTensor::F32x3([1, 1024, 3], vec![0.0; 3072]),
            );
        } else if input.name.starts_with("past_key_values") {
            cache.insert(
                input.name.clone(),
                CacheTensor::F32x4([1, 8, 0, 64], Vec::new()),
            );
        }
    }
    cache
}

fn update_cache(
    cache: &mut BTreeMap<String, CacheTensor>,
    outputs: &[(String, DynValue)],
) -> Result<(), String> {
    for (name, value) in outputs {
        if name.starts_with("present_conv") {
            let cache_name = name.replacen("present_conv", "past_conv", 1);
            let slot = cache
                .get_mut(cache_name.as_str())
                .ok_or_else(|| format!("missing cache slot: {cache_name}"))?;
            assign_cache_tensor(slot, value)?;
        } else if name.starts_with("present.") {
            let cache_name = name.replacen("present.", "past_key_values.", 1);
            let slot = cache
                .get_mut(cache_name.as_str())
                .ok_or_else(|| format!("missing cache slot: {cache_name}"))?;
            assign_cache_tensor(slot, value)?;
        }
    }
    Ok(())
}

fn assign_cache_tensor(slot: &mut CacheTensor, value: &DynValue) -> Result<(), String> {
    if let Ok(tensor) = value.try_extract_tensor::<f32>() {
        let view = tensor.view();
        let shape = view.shape().to_vec();
        let values = view
            .as_slice()
            .ok_or_else(|| "non-contiguous f32 cache tensor".to_owned())?;
        return match shape.as_slice() {
            [a, b, c] => {
                if let CacheTensor::F32x3(slot_shape, slot_values) = slot {
                    *slot_shape = [*a, *b, *c];
                    slot_values.clear();
                    slot_values.extend_from_slice(values);
                } else {
                    *slot = CacheTensor::F32x3([*a, *b, *c], values.to_vec());
                }
                Ok(())
            }
            [a, b, c, d] => {
                if let CacheTensor::F32x4(slot_shape, slot_values) = slot {
                    *slot_shape = [*a, *b, *c, *d];
                    slot_values.clear();
                    slot_values.extend_from_slice(values);
                } else {
                    *slot = CacheTensor::F32x4([*a, *b, *c, *d], values.to_vec());
                }
                Ok(())
            }
            _ => Err(format!("unsupported f32 cache shape: {shape:?}")),
        };
    }
    let tensor = value
        .try_extract_tensor::<f16>()
        .map_err(|error| format!("extract cache tensor: {error}"))?;
    let view = tensor.view();
    let shape = view.shape().to_vec();
    let values = view
        .as_slice()
        .ok_or_else(|| "non-contiguous f16 cache tensor".to_owned())?;
    match shape.as_slice() {
        [a, b, c] => {
            if let CacheTensor::F16x3(slot_shape, slot_values) = slot {
                *slot_shape = [*a, *b, *c];
                slot_values.clear();
                slot_values.extend_from_slice(values);
                Ok(())
            } else {
                *slot = CacheTensor::F16x3([*a, *b, *c], values.to_vec());
                Ok(())
            }
        }
        [a, b, c, d] => {
            if let CacheTensor::F16x4(slot_shape, slot_values) = slot {
                *slot_shape = [*a, *b, *c, *d];
                slot_values.clear();
                slot_values.extend_from_slice(values);
            } else {
                *slot = CacheTensor::F16x4([*a, *b, *c, *d], values.to_vec());
            }
            Ok(())
        }
        _ => Err(format!("unsupported f16 cache shape: {shape:?}")),
    }
}

fn extract_last_logits(value: &DynValue) -> Result<Vec<f32>, String> {
    if let Ok(tensor) = value.try_extract_tensor::<f32>() {
        let view = tensor.view();
        return last_logits(
            view.shape(),
            view.as_slice()
                .ok_or_else(|| "non-contiguous logits".to_owned())?,
        );
    }
    let tensor = value
        .try_extract_tensor::<f16>()
        .map_err(|error| format!("extract logits: {error}"))?;
    let view = tensor.view();
    let shape = view.shape().to_vec();
    let logits = view
        .as_slice()
        .ok_or_else(|| "non-contiguous fp16 logits".to_owned())?
        .iter()
        .map(|value| value.to_f32())
        .collect::<Vec<_>>();
    last_logits(&shape, &logits)
}

fn last_logits(shape: &[usize], values: &[f32]) -> Result<Vec<f32>, String> {
    let Some(&vocab) = shape.last() else {
        return Err("logits shape missing vocabulary dimension".to_owned());
    };
    if vocab == 0 || values.len() < vocab {
        return Err("logits tensor too short".to_owned());
    }
    Ok(values[values.len() - vocab..].to_vec())
}

fn argmax(values: &[f32]) -> Option<i64> {
    values
        .iter()
        .enumerate()
        .max_by(|left, right| left.1.total_cmp(right.1))
        .map(|(index, _)| index as i64)
}

fn clean_text(tokenizer: &Tokenizer, prefix: &str, tokens: &[i64]) -> Result<String, String> {
    let ids = tokens.iter().map(|&value| value as u32).collect::<Vec<_>>();
    let decoded = tokenizer
        .decode(&ids, false)
        .map_err(|error| format!("decode output: {error}"))?;
    Ok(format!("{prefix}{decoded}")
        .split("<|im_end|>")
        .next()
        .unwrap_or_default()
        .trim()
        .to_owned())
}

fn cache_stats(cache: &BTreeMap<String, CacheTensor>) -> CacheStats {
    let mut stats = CacheStats::default();
    for value in cache.values() {
        stats.kv_bytes += value.kv_bytes();
        stats.total_bytes += value.total_bytes();
    }
    stats
}

fn empty_tensor_input_f32<'a>(
    memory_info: &MemoryInfo,
    shape: Vec<i64>,
) -> Result<TensorRefMut<'a, f32>, String> {
    static ZERO: [f32; 1] = [0.0];
    unsafe {
        TensorRefMut::<f32>::from_raw(memory_info.clone(), ZERO.as_ptr().cast_mut().cast(), shape)
            .map_err(|error| format!("create empty f32 tensor: {error}"))
    }
}

fn empty_tensor_input_f16<'a>(
    memory_info: &MemoryInfo,
    shape: Vec<i64>,
) -> Result<TensorRefMut<'a, f16>, String> {
    static ZERO: [f16; 1] = [f16::from_bits(0)];
    unsafe {
        TensorRefMut::<f16>::from_raw(memory_info.clone(), ZERO.as_ptr().cast_mut().cast(), shape)
            .map_err(|error| format!("create empty f16 tensor: {error}"))
    }
}

pub fn cpu_input_memory_info() -> Result<MemoryInfo, String> {
    MemoryInfo::new(
        AllocationDevice::CPU,
        0,
        AllocatorType::Arena,
        MemoryType::CPUInput,
    )
    .map_err(|error| format!("cpu input memory info: {error}"))
}

fn tensor_ref_from_i64_buffer<'a>(
    memory_info: &MemoryInfo,
    buffer: &'a mut Vec<i64>,
    shape: Vec<i64>,
    label: &str,
) -> Result<TensorRefMut<'a, i64>, String> {
    unsafe {
        TensorRefMut::from_raw(memory_info.clone(), buffer.as_mut_ptr().cast(), shape)
            .map_err(|error| format!("{label}: {error}"))
    }
}

fn tensor_ref_from_f32_cache<'a>(
    memory_info: &MemoryInfo,
    buffer: &'a mut Vec<f32>,
    shape: Vec<i64>,
    label: &str,
) -> Result<TensorRefMut<'a, f32>, String> {
    if shape.iter().any(|&dim| dim == 0) {
        return empty_tensor_input_f32(memory_info, shape);
    }
    unsafe {
        TensorRefMut::from_raw(memory_info.clone(), buffer.as_mut_ptr().cast(), shape)
            .map_err(|error| format!("{label}: {error}"))
    }
}

fn tensor_ref_from_f16_cache<'a>(
    memory_info: &MemoryInfo,
    buffer: &'a mut Vec<f16>,
    shape: Vec<i64>,
    label: &str,
) -> Result<TensorRefMut<'a, f16>, String> {
    if shape.iter().any(|&dim| dim == 0) {
        return empty_tensor_input_f16(memory_info, shape);
    }
    unsafe {
        TensorRefMut::from_raw(memory_info.clone(), buffer.as_mut_ptr().cast(), shape)
            .map_err(|error| format!("{label}: {error}"))
    }
}

fn average(values: &[f64]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f64>() / values.len() as f64
    }
}
