use std::collections::BTreeMap;

use anyhow::{Result, bail};
use gliner25_rs::overlap::OverlapPolicy;
use gliner25_rs::processor::SchemaTask;

use super::{FeatureEngine, RawMention};
use crate::chunk::chapter_windows;

impl FeatureEngine {
    pub fn extract_entities_long(
        &mut self,
        text: &str,
        labels: &[String],
        chunk_words: usize,
        overlap_words: usize,
        threshold: f32,
    ) -> Result<Vec<RawMention>> {
        if chunk_words == 0 || overlap_words >= chunk_words {
            bail!("long-context windows require 0 <= overlap < chunk size");
        }
        let maximum = self
            .manifest()
            .length_buckets
            .iter()
            .copied()
            .max()
            .unwrap_or(0);
        if chunk_words > maximum {
            bail!("chunk size {chunk_words} exceeds model bucket {maximum}");
        }
        let mut merged: BTreeMap<(String, usize, usize), RawMention> = BTreeMap::new();
        for chunk in chapter_windows(text, chunk_words, overlap_words) {
            let body = chunk.text(text);
            let trace = self.trace(body, &[SchemaTask::Entities(labels.to_vec())])?;
            for mut mention in self.decode_mentions(&trace, threshold, labels, OverlapPolicy::Flat)
            {
                mention.char_start += chunk.byte_start;
                mention.char_end += chunk.byte_start;
                mention.word_start += chunk.word_start as usize;
                mention.word_end += chunk.word_start as usize;
                let key = (mention.field.clone(), mention.char_start, mention.char_end);
                if merged.get(&key).is_none_or(|old| mention.score > old.score) {
                    merged.insert(key, mention);
                }
            }
        }
        let mut output: Vec<RawMention> = merged.into_values().collect();
        output.sort_by(|a, b| {
            a.char_start
                .cmp(&b.char_start)
                .then(a.char_end.cmp(&b.char_end))
                .then(a.field.cmp(&b.field))
        });
        Ok(output)
    }
}

#[cfg(test)]
mod tests {
    use crate::chunk::chapter_windows;

    #[test]
    fn overlap_windows_retain_tail_evidence() {
        let text = (0..900)
            .map(|index| format!("filler{index}"))
            .chain([
                "OpenAI".into(),
                "appointed".into(),
                "Sam".into(),
                "Altman".into(),
            ])
            .collect::<Vec<_>>()
            .join(" ");
        let chunks = chapter_windows(&text, 384, 64);
        assert!(chunks.len() >= 3);
        assert!(chunks.last().unwrap().text(&text).contains("Sam Altman"));
    }
}
