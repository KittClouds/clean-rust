use std::fs;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use anyhow::{Context, Result};
use jev_decision_world_v01::{GenerationConfig, all_templates, generate_episode};
use jev_decision_world_v02::adapters::{
    chaos_nli, clinc_oos, docred, go_emotions, massive, multitask_classification, tasksource,
};
use jev_decision_world_v02::structured::{StructuredRenderer, structured_span_relation_episode};
use jev_decision_world_v02::synthetic::from_v01;
use jev_decision_world_v02::types::CanonicalEpisode;
use serde::Serialize;

use jev_corpus_bridge_v01::{census, overlap, source_registry, splits, validate_all};

#[derive(Clone, Debug, Serialize)]
struct MixedPilotManifest {
    mixture_id: String,
    status: String,
    sources: Vec<MixSource>,
    episode_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
struct MixSource {
    source: String,
    weight: f64,
    selected_for_pilot: bool,
    note: String,
}

fn main() -> Result<()> {
    let output_dir = PathBuf::from(r"D:\codex-runs\jev-corpus-bridge-v01");
    fs::create_dir_all(&output_dir).with_context(|| format!("create {}", output_dir.display()))?;
    let synthetic_per_template = std::env::var("JEV_SYNTHETIC_PER_TEMPLATE")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(2)
        .max(1);
    let episodes = pilot_episodes(synthetic_per_template)?;
    validate_all(&episodes)?;
    write_jsonl(&output_dir.join("pilot-episodes.jsonl"), &episodes)?;
    write_json(
        &output_dir.join("source-audit.json"),
        &source_registry::profiles(),
    )?;
    write_json(
        &output_dir.join("semantic-census.json"),
        &census::census(&episodes),
    )?;
    write_json(
        &output_dir.join("source-overlap-report.json"),
        &overlap::audit(&episodes),
    )?;
    write_json(
        &output_dir.join("split-leakage-report.json"),
        &splits::build(&episodes),
    )?;
    let manifest = MixedPilotManifest {
        mixture_id: "jev-mixed-pilot-v0.2".to_string(),
        status: "research_pilot_manifest; weights not frozen".to_string(),
        sources: vec![
            MixSource {
                source: "synthetic_control".to_string(),
                weight: 0.20,
                selected_for_pilot: true,
                note: "exact finite-world conversion".to_string(),
            },
            MixSource {
                source: "hard_choice".to_string(),
                weight: 0.20,
                selected_for_pilot: true,
                note:
                    "multitask/tasksource pinned viewer samples plus fixtures; CLINC fixture lane"
                        .to_string(),
            },
            MixSource {
                source: "human_disagreement".to_string(),
                weight: 0.20,
                selected_for_pilot: true,
                note: "ChaosNLI and raw GoEmotions fixture plus pinned viewer sample lanes"
                    .to_string(),
            },
            MixSource {
                source: "abstention".to_string(),
                weight: 0.10,
                selected_for_pilot: true,
                note: "CLINC OOS fixture lane".to_string(),
            },
            MixSource {
                source: "span_type".to_string(),
                weight: 0.15,
                selected_for_pilot: true,
                note: "MASSIVE and synthetic structured control".to_string(),
            },
            MixSource {
                source: "relation_evidence".to_string(),
                weight: 0.15,
                selected_for_pilot: true,
                note: "DocRED and synthetic structured control".to_string(),
            },
        ],
        episode_ids: episodes
            .iter()
            .map(|episode| episode.identity.episode_id.clone())
            .collect(),
    };
    write_json(&output_dir.join("mixed-pilot-manifest.json"), &manifest)?;
    println!(
        "validated_episodes={} output_dir={}",
        episodes.len(),
        output_dir.display()
    );
    Ok(())
}

fn pilot_episodes(synthetic_per_template: usize) -> Result<Vec<CanonicalEpisode>> {
    let mut episodes = Vec::new();
    let config = GenerationConfig {
        seed: 0x4a45_5602,
        count: 1,
        visibility_probability: 0.80,
    };
    for (template_index, template) in all_templates().into_iter().enumerate() {
        for offset in 0..synthetic_per_template {
            let source = generate_episode(
                &template,
                template_index * synthetic_per_template + offset,
                &config,
            )?;
            episodes.push(from_v01(&source, &template)?);
        }
    }
    episodes.push(structured_span_relation_episode(
        StructuredRenderer::MaraFirst,
    )?);
    episodes.push(structured_span_relation_episode(
        StructuredRenderer::OrionFirst,
    )?);
    episodes.push(multitask_fixture()?);
    episodes.push(multitask_live_sample()?);
    episodes.push(tasksource_fixture()?);
    episodes.push(tasksource_live_sample()?);
    episodes.push(chaos_fixture()?);
    episodes.extend(go_emotions::normalize_group(
        &go_emotions_fixture(),
        "add492243ff905527e67aeb8b80c082af02207c3",
        "train",
    )?);
    episodes.extend(go_emotions::normalize_group(
        &go_emotions_live_sample(),
        "add492243ff905527e67aeb8b80c082af02207c3",
        "train",
    )?);
    episodes.push(clinc_oos::normalize_row(
        &serde_json::json!({"text":"I need to reserve a flight","intent":"book_flight"}),
        "clinc-0",
        "828f8093932c8fe6ca7936c3d2e52903b1c523de",
        "train",
        &clinc_inventory(),
    )?);
    episodes.push(clinc_oos::normalize_row(&serde_json::json!({"text":"Tell me something outside the supported intents","intent":"oos"}), "clinc-oos-0", "828f8093932c8fe6ca7936c3d2e52903b1c523de", "oos", &clinc_inventory())?);
    episodes.push(massive_fixture()?);
    episodes.push(docred_fixture()?);
    Ok(episodes)
}

fn multitask_fixture() -> Result<CanonicalEpisode> {
    let input = serde_json::json!({"text":"A credential was used from a new device.","instructions":"Choose the incident class.","choices":{"credential_compromise":"Unauthorized access using valid credentials.","maintenance":"A planned change explains the activity.","benign_activity":"The activity is ordinary."}}).to_string();
    multitask_classification::normalize_row(
        &serde_json::json!({"input":input,"label":[1.0,0.0,0.0]}),
        "fixture-0",
        "795d472566a56aa94b139e3e041d2088527f30af",
        "train",
    )
}

fn tasksource_fixture() -> Result<CanonicalEpisode> {
    tasksource::normalize_row(
        &serde_json::json!({"premise":"The door is open.","hypothesis":"The door is closed.","task":"fixture-nli","labels":2}),
        "fixture-0",
        "ee693dba923b5d5484aa9232b7357c5e45dd39b8",
        "train",
    )
}

fn multitask_live_sample() -> Result<CanonicalEpisode> {
    let input = serde_json::json!({
        "text":"tengeneza orodha mpya ya aina ya mbwa",
        "instructions":"Classify the assistant request by its scenario or domain.",
        "choices":{
            "social":"The request concerns social media posts or social interactions.",
            "transport":"The request concerns transportation, traffic, tickets, or taxis.",
            "calendar":"The request concerns calendar events, appointments, or schedules.",
            "play":"The request asks to play media such as music, radio, podcasts, or audiobooks, or to play a game.",
            "news":"The request concerns news or current events.",
            "datetime":"The request concerns the date, time, or time zones.",
            "recommendation":"The request seeks recommendations for events, places, or movies.",
            "email":"The request concerns email messages or email contacts.",
            "iot":"The request controls connected home devices such as lights, plugs, or appliances.",
            "general":"The request is a general conversation, greeting, joke, or assistant interaction.",
            "audio":"The request controls audio volume or muting.",
            "lists":"The request creates, retrieves, or edits a list.",
            "qa":"The request asks a factual question or seeks general information.",
            "cooking":"The request concerns cooking, recipes, or cooking times.",
            "takeaway":"The request concerns ordering takeaway food or checking an order.",
            "music":"The request concerns music preferences, song information, or music settings.",
            "alarm":"The request concerns setting, querying, or removing an alarm.",
            "weather":"The request concerns weather conditions or forecasts."
        }
    }).to_string();
    let mut labels = vec![0.0; 18];
    labels[11] = 1.0;
    multitask_classification::normalize_row(
        &serde_json::json!({"input":input,"label":labels}),
        "hf-train-0",
        "795d472566a56aa94b139e3e041d2088527f30af",
        "train",
    )
}

fn tasksource_live_sample() -> Result<CanonicalEpisode> {
    tasksource::normalize_row(
        &serde_json::json!({
            "labels":2,
            "premise":"Amrozi accused his brother , whom he called \" the witness \" , of deliberately distorting his evidence .\nReferring to him as only \" the witness \" , Amrozi accused his brother of deliberately distorting his evidence.",
            "hypothesis":"This example is not_equivalent.",
            "task":"glue/mrpc"
        }),
        "hf-train-0",
        "ee693dba923b5d5484aa9232b7357c5e45dd39b8",
        "train",
    )
}

fn chaos_fixture() -> Result<CanonicalEpisode> {
    chaos_nli::normalize_row(
        &serde_json::json!({"uid":"chaos-fixture-0","example":{"premise":"A person is running.","hypothesis":"A person is moving.","source":"SNLI"},"label_count":[78,17,5],"majority_label":"e"}),
        "chaos-fixture-0",
        "f358e234ea2797d9298f7b0213bf1308b6d7756b",
        "source-native",
    )
}

fn go_emotions_fixture() -> Vec<serde_json::Value> {
    vec![
        emotion_row(
            "emotion-fixture-0",
            1,
            "I am delighted that this worked.",
            "joy",
        ),
        emotion_row(
            "emotion-fixture-0",
            2,
            "I am delighted that this worked.",
            "joy",
        ),
        emotion_row(
            "emotion-fixture-0",
            3,
            "I am delighted that this worked.",
            "surprise",
        ),
    ]
}

fn emotion_row(id: &str, rater_id: i64, text: &str, label: &str) -> serde_json::Value {
    let mut row = serde_json::Map::new();
    row.insert("id".to_string(), serde_json::json!(id));
    row.insert("rater_id".to_string(), serde_json::json!(rater_id));
    row.insert("text".to_string(), serde_json::json!(text));
    for emotion in go_emotions::EMOTIONS {
        row.insert(
            (*emotion).to_string(),
            serde_json::json!(if *emotion == label { 1 } else { 0 }),
        );
    }
    serde_json::Value::Object(row)
}

fn go_emotions_live_sample() -> Vec<serde_json::Value> {
    vec![emotion_row("eew5j0j", 1, "That game hurt.", "sadness")]
}

fn clinc_inventory() -> Vec<String> {
    vec![
        "book_flight".to_string(),
        "pay_bill".to_string(),
        "oos".to_string(),
    ]
}

fn massive_fixture() -> Result<CanonicalEpisode> {
    massive::normalize_row(
        &serde_json::json!({"utt":"Transfer 42 to Mara","annot_utt":"Transfer [account_type : 42] to [person_name : Mara]","intent":"transfer_money"}),
        "fixture-0",
        "ff6bd8e4b27c3543e4f8fe2108f32bb95a6f8740",
        "train",
        "en-US",
    )
}

fn docred_fixture() -> Result<CanonicalEpisode> {
    docred::normalize_row(
        &serde_json::json!({
            "title":"Fixture",
            "sents":[["Mara","gave","the","key","to","Orion","."],["The","transfer","was","recorded","."]],
            "vertexSet":[
                [{"name":"Mara","sent_id":0,"pos":[0,1],"type":"PERSON"}],
                [{"name":"key","sent_id":0,"pos":[3,4],"type":"OBJECT"}],
                [{"name":"Orion","sent_id":0,"pos":[5,6],"type":"PERSON"}]
            ],
            "labels":[{"h":1,"t":2,"r":1,"relation_text":"transferred_to","evidence":[0]}]
        }),
        "fixture-0",
        "7985b4e0371e6c61a756feb41b7b27becf71c666",
        "train_annotated",
    )
}

fn write_json<T: Serialize>(path: &PathBuf, value: &T) -> Result<()> {
    fs::write(path, serde_json::to_vec_pretty(value)?)
        .with_context(|| format!("write {}", path.display()))?;
    Ok(())
}

fn write_jsonl<T: Serialize>(path: &PathBuf, values: &[T]) -> Result<()> {
    let file = fs::File::create(path).with_context(|| format!("create {}", path.display()))?;
    let mut writer = BufWriter::new(file);
    for value in values {
        serde_json::to_writer(&mut writer, value)?;
        writer.write_all(b"\n")?;
    }
    writer
        .flush()
        .with_context(|| format!("flush {}", path.display()))?;
    Ok(())
}
