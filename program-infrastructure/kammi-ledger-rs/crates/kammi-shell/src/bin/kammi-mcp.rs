//! `kammi-mcp`: the narrow stdio MCP server (`KAMMI_URL`, `KAMMI_TOKEN`).

fn main() {
    let client = match kammi_shell::client::Client::from_environment() {
        Ok(client) => client,
        Err(error) => {
            eprintln!("kammi-mcp: {error}");
            std::process::exit(kammi_contract::verbs::exit::USAGE);
        }
    };
    if let Err(error) = kammi_shell::mcp::serve(kammi_shell::mcp::Mcp::new(client)) {
        eprintln!("kammi-mcp: {error}");
        std::process::exit(1);
    }
}
