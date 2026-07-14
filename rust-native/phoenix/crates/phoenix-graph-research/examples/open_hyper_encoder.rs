use phoenix_graph_research::HyperEncoderMapped;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args_os().nth(1).ok_or("model manifest")?;
    let model = HyperEncoderMapped::open(path)?;
    println!("{}", model.manifest().model_id);
    Ok(())
}
