pub fn split_sentence_ranges(text: &str) -> Vec<(usize, usize)> {
    phoenix_chunker_native::split_sentence_ranges(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_sentence_ranges_respects_short_guards() {
        let text = "Dr. Luffy ran. Mr. Zoro stayed. Wow!";
        let ranges = split_sentence_ranges(text);
        assert_eq!(ranges.len(), 3);
        assert_eq!(&text[ranges[0].0..ranges[0].1], "Dr. Luffy ran.");
        assert_eq!(&text[ranges[1].0..ranges[1].1], "Mr. Zoro stayed.");
        assert_eq!(&text[ranges[2].0..ranges[2].1], "Wow!");
    }

    #[test]
    fn split_sentence_ranges_handles_empty_input() {
        assert!(split_sentence_ranges("").is_empty());
    }
}
