mod document_index_read;
mod graph_galaxy;
mod graph_run_store;
mod graph_scene_packet;
mod native_decision_rpc;
mod nli_claim_rpc;
mod phoenix_rpc;
mod tts;

use phoenix_rpc::{PhoenixApi, PhoenixApiImpl};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(taurpc::create_ipc_handler(
            PhoenixApiImpl::default().into_handler(),
        ))
        .run(tauri::generate_context!())
        .expect("error while running Phoenix Tauri shell");
}

#[cfg(test)]
mod contract_tests {
    use super::*;

    #[test]
    fn export_phoenix_contract() {
        let _handler = taurpc::create_ipc_handler::<_, tauri::test::MockRuntime>(
            PhoenixApiImpl::default().into_handler(),
        );
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../src/app/generated/phoenix-taurpc.ts");
        let generated = std::fs::read_to_string(&path).expect("read generated TauRPC contract");
        let normalized = generated
            .lines()
            .map(str::trim_end)
            .collect::<Vec<_>>()
            .join("\n")
            + "\n";
        if generated != normalized {
            std::fs::write(path, normalized).expect("normalize generated TauRPC contract");
        }
    }
}
