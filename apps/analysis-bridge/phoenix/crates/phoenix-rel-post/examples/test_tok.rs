use tokenizers::Tokenizer;

fn main() {
    let tk =
        Tokenizer::from_file("../../../../gliner-bi-small-onnx/labels_tokenizer/tokenizer.json")
            .unwrap();
    let encoding = tk.encode("Person", false).unwrap();
    println!("Person IDs: {:?}", encoding.get_ids());
    println!("Person Tokens: {:?}", encoding.get_tokens());

    let encoding2 = tk.encode("Organization", false).unwrap();
    println!("Organization IDs: {:?}", encoding2.get_ids());
    println!("Organization Tokens: {:?}", encoding2.get_tokens());
}
