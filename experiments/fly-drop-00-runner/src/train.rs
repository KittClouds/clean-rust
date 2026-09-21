use crate::model::{binary_cross_entropy, Cache, Model, PARAMS, WIDTH};
use crate::util::{hex, sha256_file, write_new_json};
use anyhow::{Context, Result, ensure};
use memmap2::Mmap;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub struct Operator { matrix: Vec<f64>, transpose: Vec<f64> }
pub struct TeacherData { train_x: Mmap, train_y: Mmap }

pub fn load_operators(manifest: &Value) -> Result<HashMap<String, Operator>> {
    let rows = manifest["operators"].as_array().context("operator inventory missing")?;
    let mut operators = HashMap::with_capacity(rows.len());
    for row in rows {
        let id = row["operator_id"].as_str().context("operator ID missing")?.to_owned();
        let path = PathBuf::from(row["matrix_file"].as_str().context("operator path missing")?);
        ensure!(sha256_file(&path)? == row["matrix_sha256"].as_str().unwrap(), "operator changed: {}", path.display());
        let bytes = fs::read(&path)?;
        ensure!(bytes.len() == WIDTH * WIDTH * 8, "operator has wrong dimensions: {}", path.display());
        let matrix: Vec<f64> = bytes.chunks_exact(8)
            .map(|chunk| f64::from_le_bytes(chunk.try_into().unwrap())).collect();
        ensure!(matrix.iter().all(|x| x.is_finite()), "operator contains nonfinite values: {}", path.display());
        let mut transpose = vec![0.0; matrix.len()];
        for r in 0..WIDTH { for c in 0..WIDTH { transpose[c * WIDTH + r] = matrix[r * WIDTH + c]; } }
        ensure!(operators.insert(id, Operator { matrix, transpose }).is_none(), "duplicate operator ID");
    }
    ensure!(operators.len() == 41, "operator inventory is not 41");
    Ok(operators)
}

pub fn load_training_data(manifest: &Value) -> Result<HashMap<u64, TeacherData>> {
    let worlds = manifest["teacher_worlds"].as_array().context("teacher inventory missing")?;
    let mut result = HashMap::with_capacity(worlds.len());
    for world in worlds {
        let seed = world["seed"].as_u64().context("teacher seed missing")?;
        let train_x = checked_map(&world["files"]["train_x"])?;
        let train_y = checked_map(&world["files"]["train_y"])?;
        ensure!(train_x.len() == 8192 * WIDTH * 4, "training features have wrong shape");
        ensure!(train_y.len() == 8192, "training labels have wrong shape");
        ensure!(train_y.iter().all(|y| *y <= 1), "training labels are not binary");
        ensure!(result.insert(seed, TeacherData { train_x, train_y }).is_none(), "duplicate teacher seed");
    }
    ensure!(result.len() == 4, "teacher inventory is not four worlds");
    Ok(result)
}

fn checked_map(record: &Value) -> Result<Mmap> {
    let path = PathBuf::from(record["path"].as_str().context("data path missing")?);
    ensure!(sha256_file(&path)? == record["sha256"].as_str().unwrap(), "input changed: {}", path.display());
    let file = File::open(&path)?;
    // SAFETY: all mapped source artifacts are sealed immutable inputs; the runner only reads them.
    let map = unsafe { Mmap::map(&file)? };
    ensure!(map.len() == record["bytes"].as_u64().unwrap() as usize, "input byte length changed: {}", path.display());
    Ok(map)
}

pub fn execute_fit(fit: &Value, run_dir: &Path, operators: &HashMap<String, Operator>, data: &HashMap<u64, TeacherData>) -> Result<bool> {
    let collection = run_dir.join("collection");
    let fit_id = fit["fit_id"].as_str().context("fit ID missing")?;
    let fit_prefix = format!("{fit_id}.attempt-");
    let receipts_dir = collection.join("fit-receipts");
    let attempts_dir = collection.join("attempts");
    fs::create_dir_all(collection.join("evaluation-access"))?;
    fs::create_dir_all(&receipts_dir)?;
    fs::create_dir_all(&attempts_dir)?;
    let mut highest_attempt = 0u32;
    for entry in fs::read_dir(&receipts_dir)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with(&fit_prefix) && name.ends_with(".json") {
            if let Ok(bytes) = fs::read(entry.path()) {
                if let Ok(receipt) = serde_json::from_slice::<Value>(&bytes) {
                    if receipt["fit_id"].as_str() == Some(fit_id)
                        && matches!(receipt["status"].as_str(), Some("complete" | "numerical_failure")) {
                        return Ok(false);
                    }
                }
            }
            highest_attempt = highest_attempt.max(attempt_number(&name));
        }
    }
    for entry in fs::read_dir(&attempts_dir)? {
        let name = entry?.file_name().to_string_lossy().to_string();
        if name.starts_with(&fit_prefix) { highest_attempt = highest_attempt.max(attempt_number(&name)); }
    }
    let attempt = highest_attempt + 1;
    let attempt_id = format!("{fit_id}.attempt-{attempt:04}");
    let started = now_unix_ms();
    write_new_json(&attempts_dir.join(format!("{attempt_id}.start.json")), &json!({
        "fit_id": fit_id, "attempt": attempt, "started_unix_ms": started,
        "run_id": "FLY-DROP-00-RUN1", "manifest_row_sha256": hex(&crate::util::sha256(&serde_json::to_vec(fit)?)),
    }))?;

    let started_at = Instant::now();
    let operator_id = fit["operator_id"].as_str().context("operator ID missing")?;
    let operator = operators.get(operator_id).context("unknown operator ID")?;
    let teacher_seed = fit["teacher_seed"].as_u64().context("teacher seed missing")?;
    let world = data.get(&teacher_seed).context("unknown teacher seed")?;
    let init_path = PathBuf::from(fit["initial_parameters"]["path"].as_str().unwrap());
    let order_path = PathBuf::from(fit["minibatch_order"]["path"].as_str().unwrap());
    ensure!(sha256_file(&init_path)? == fit["initial_parameters"]["sha256"].as_str().unwrap(), "initial parameters changed");
    ensure!(sha256_file(&order_path)? == fit["minibatch_order"]["sha256"].as_str().unwrap(), "minibatch order changed");
    let initial = fs::read(&init_path)?;
    let order_bytes = fs::read(&order_path)?;
    ensure!(initial.len() == PARAMS * 4, "initial parameter vector has wrong shape");
    ensure!(order_bytes.len() == 20 * 8192 * 4, "minibatch order has wrong shape");
    let order: &[u32] = bytemuck::try_cast_slice(&order_bytes).map_err(|e| anyhow::anyhow!(e.to_string()))?;
    ensure!(order.iter().all(|i| *i < 8192), "minibatch order index out of range");
    let mut model = Model::from_initial(&initial)?;
    let mut grad = vec![0.0f32; PARAMS];
    let mut cache = Cache::default();
    let train_x: &[f32] = bytemuck::try_cast_slice(&world.train_x[..]).map_err(|e| anyhow::anyhow!(e.to_string()))?;
    let mut epoch_losses = Vec::with_capacity(20);
    let mut numerical_failure_update: Option<u64> = None;
    let mut step = 0u64;

    for epoch in 0..20 {
        let mut loss_sum = 0.0f64;
        let epoch_order = &order[epoch * 8192..(epoch + 1) * 8192];
        for batch in 0..64 {
            grad.fill(0.0);
            let mut batch_loss = 0.0f64;
            for &sample in &epoch_order[batch * 128..(batch + 1) * 128] {
                let idx = sample as usize;
                let x = &train_x[idx * WIDTH..(idx + 1) * WIDTH];
                let label = world.train_y[idx];
                model.forward(x, &operator.matrix, &mut cache);
                batch_loss += binary_cross_entropy(cache.logit(), label);
                model.backward(x, label, &operator.transpose, &mut cache, &mut grad);
            }
            model.adamw_step(&mut grad, step + 1);
            step += 1;
            loss_sum += batch_loss;
            if numerical_failure_update.is_none()
                && (!model.finite_state() || !batch_loss.is_finite() || grad.iter().any(|g| !g.is_finite())) {
                numerical_failure_update = Some(step);
            }
        }
        epoch_losses.push(loss_sum / 8192.0);
    }
    ensure!(step == 1280, "fit did not complete 1280 updates");

    // This event is written only after the final optimizer update and immediately before
    // mapping the sealed held-out bytes for the single terminal evaluation pass.
    write_new_json(&collection.join("evaluation-access").join(format!("{attempt_id}.json")), &json!({
        "fit_id": fit_id, "attempt": attempt, "optimizer_updates": step,
        "access": "terminal_heldout_evaluation", "planned_passes": 1, "unix_ms": now_unix_ms(),
    }))?;
    let heldout_x = checked_map(&fit["input_files"]["heldout_x"])?;
    let heldout_y = checked_map(&fit["input_files"]["heldout_y"])?;
    ensure!(heldout_x.len() == 4096 * WIDTH * 4 && heldout_y.len() == 4096, "held-out data have wrong shape");
    ensure!(heldout_y.iter().all(|y| *y <= 1), "held-out labels are not binary");
    let heldout_x_f32: &[f32] = bytemuck::try_cast_slice(&heldout_x[..]).map_err(|e| anyhow::anyhow!(e.to_string()))?;
    let (heldout_bce, heldout_accuracy, eval_finite) = evaluate(&model, &operator.matrix, heldout_x_f32, &heldout_y, &mut cache);
    if !eval_finite && numerical_failure_update.is_none() { numerical_failure_update = Some(step); }
    let final_param_bytes: &[u8] = bytemuck::cast_slice(&model.p);
    let final_params_hash = hex(&crate::util::sha256(final_param_bytes));
    let status = if numerical_failure_update.is_some() { "numerical_failure" } else { "complete" };
    let receipt = json!({
        "schema": "FLY-DROP-00-fit-receipt-v1", "run_id": "FLY-DROP-00-RUN1",
        "fit_id": fit_id, "attempt": attempt, "status": status,
        "operator_id": operator_id, "arm": fit["arm"], "adapter_seed": fit["adapter_seed"],
        "graph_realization": fit["graph_realization"], "control_seed": fit["control_seed"],
        "teacher_seed": teacher_seed, "learner_seed": fit["learner_seed"],
        "operator_sha256": fit["operator_sha256"], "input_hashes": fit["input_hashes"],
        "initial_parameters_sha256": fit["initial_parameters"]["sha256"],
        "minibatch_order_sha256": fit["minibatch_order"]["sha256"],
        "paired_initialization_fingerprint": fit["paired_initialization_fingerprint"],
        "paired_order_fingerprint": fit["paired_order_fingerprint"],
        "optimizer_updates": step, "epochs_completed": 20,
        "terminal_eval_update_count": step, "terminal_eval_passes": 1,
        "final_parameter_sha256": final_params_hash,
        "final_train_loss": finite_or_null(*epoch_losses.last().unwrap()),
        "heldout_bce": option_number(heldout_bce), "heldout_accuracy": option_number(heldout_accuracy),
        "numerical_status": if numerical_failure_update.is_some() { "nonfinite_detected" } else { "finite" },
        "first_nonfinite_update": numerical_failure_update,
        "epoch_train_loss": epoch_losses.iter().map(|&x| finite_or_null(x)).collect::<Vec<_>>(),
        "runtime_seconds": started_at.elapsed().as_secs_f64(),
        "attempt_started_unix_ms": started, "finished_unix_ms": now_unix_ms(),
    });
    let receipt_path = receipts_dir.join(format!("{attempt_id}.json"));
    write_new_json(&receipt_path, &receipt)?;
    write_new_json(&attempts_dir.join(format!("{attempt_id}.end.json")), &json!({
        "fit_id": fit_id, "attempt": attempt, "finished_unix_ms": now_unix_ms(),
        "receipt_path": receipt_path.to_string_lossy(), "receipt_sha256": sha256_file(&receipt_path)?,
        "status": status,
    }))?;
    Ok(true)
}

fn evaluate(model: &Model, matrix: &[f64], features: &[f32], labels: &[u8], cache: &mut Cache) -> (f64, f64, bool) {
    let mut total_loss = 0.0f64;
    let mut correct = 0usize;
    let mut finite = true;
    for (i, &label) in labels.iter().enumerate() {
        let x = &features[i * WIDTH..(i + 1) * WIDTH];
        model.forward(x, matrix, cache);
        let loss = binary_cross_entropy(cache.logit(), label);
        if !loss.is_finite() || !cache.logit().is_finite() { finite = false; }
        total_loss += loss;
        if cache.logit().is_finite() && ((cache.logit() >= 0.0) == (label == 1)) { correct += 1; }
    }
    if finite { (total_loss / labels.len() as f64, correct as f64 / labels.len() as f64, true) }
    else { (f64::NAN, f64::NAN, false) }
}

fn attempt_number(name: &str) -> u32 {
    name.split(".attempt-").nth(1).and_then(|part| part.get(..4))
        .and_then(|digits| digits.parse().ok()).unwrap_or(0)
}

fn now_unix_ms() -> u128 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis()
}

fn finite_or_null(value: f64) -> Value { if value.is_finite() { json!(value) } else { Value::Null } }
fn option_number(value: f64) -> Option<f64> { if value.is_finite() { Some(value) } else { None } }

pub fn write_collection_tables(fits: &[Value], run_dir: &Path) -> Result<()> {
    let collection = run_dir.join("collection");
    let receipts = collection.join("fit-receipts");
    let mut indexed: HashMap<String, Value> = HashMap::with_capacity(fits.len());
    for entry in fs::read_dir(&receipts)? {
        let path = entry?.path();
        if path.extension().and_then(|x| x.to_str()) != Some("json") { continue; }
        let receipt: Value = serde_json::from_slice(&fs::read(&path)?)?;
        if let Some(id) = receipt["fit_id"].as_str() {
            let keep = indexed.get(id).is_none_or(|old| receipt["attempt"].as_u64() > old["attempt"].as_u64());
            if keep { indexed.insert(id.to_owned(), receipt); }
        }
    }
    let mut outcomes = String::from("fit_id,operator_id,arm,adapter_seed,graph_realization,control_seed,teacher_seed,learner_seed,status,heldout_bce,heldout_accuracy,final_train_loss\n");
    let mut epochs = String::from("fit_id,operator_id,arm,teacher_seed,learner_seed,epoch,train_loss\n");
    for fit in fits {
        let id = fit["fit_id"].as_str().unwrap();
        let receipt = indexed.get(id).with_context(|| format!("missing receipt for {id}"))?;
        outcomes.push_str(&format!("{},{},{},{},{},{},{},{},{},{},{},{}\n",
            csv(id), csv(receipt["operator_id"].as_str().unwrap_or("")), csv(receipt["arm"].as_str().unwrap_or("")),
            csv_opt(&receipt["adapter_seed"]), csv_opt(&receipt["graph_realization"]), csv_opt(&receipt["control_seed"]),
            csv_opt(&receipt["teacher_seed"]), csv_opt(&receipt["learner_seed"]), csv(receipt["status"].as_str().unwrap_or("")),
            csv_opt(&receipt["heldout_bce"]), csv_opt(&receipt["heldout_accuracy"]), csv_opt(&receipt["final_train_loss"])));
        if let Some(losses) = receipt["epoch_train_loss"].as_array() {
            for (epoch, loss) in losses.iter().enumerate() {
                epochs.push_str(&format!("{},{},{},{},{},{},{}\n", csv(id), csv(receipt["operator_id"].as_str().unwrap_or("")),
                    csv(receipt["arm"].as_str().unwrap_or("")), csv_opt(&receipt["teacher_seed"]), csv_opt(&receipt["learner_seed"]), epoch + 1, csv_opt(loss)));
            }
        }
    }
    write_create_new(&collection.join("final-outcomes.csv"), outcomes.as_bytes())?;
    write_create_new(&collection.join("epoch-metrics.csv"), epochs.as_bytes())?;
    Ok(())
}

fn write_create_new(path: &Path, bytes: &[u8]) -> Result<()> {
    if path.exists() {
        ensure!(fs::read(path)? == bytes, "existing immutable collection table differs: {}", path.display());
        return Ok(());
    }
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn csv(value: &str) -> String { format!("\"{}\"", value.replace('"', "\"\"")) }
fn csv_opt(value: &Value) -> String {
    match value { Value::Null => String::new(), Value::String(x) => csv(x), _ => value.to_string() }
}
