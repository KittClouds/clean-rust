mod document_index_read;
mod graph_galaxy;
mod graph_scene_packet;
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
