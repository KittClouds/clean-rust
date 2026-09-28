use std::cmp::Ordering;

use half::f16;
use ort::value::DynValue;
use tokenizers::Tokenizer;

use crate::gliner_x::{GlinerXError, GlinerXPrediction};

#[derive(Clone, Debug)]
pub(super) struct WordSpan {
    pub(super) start: usize,
    pub(super) end: usize,
}

#[derive(Clone, Debug)]
pub(super) struct GlinerXTextTensors {
    pub(super) words: Vec<WordSpan>,
    pub(super) input_ids: Vec<i64>,
    pub(super) attention_mask: Vec<i64>,
    pub(super) words_mask: Vec<i64>,
}

pub(super) fn build_text_tensors(
    text: &str,
    tokenizer: &Tokenizer,
    labels: &[String],
    ent_token: &str,
    sep_token: &str,
    max_len: usize,
) -> Result<Option<GlinerXTextTensors>, GlinerXError> {
    let words = words_splitter_limited(text, max_len);
    if words.is_empty() {
        return Ok(None);
    }

    let prompt_word_count = labels.len() * 2 + 1;
    let mut pieces = Vec::with_capacity(prompt_word_count + words.len());
    for label in labels {
        pieces.push(ent_token);
        pieces.push(label.as_str());
    }
    pieces.push(sep_token);
    pieces.extend(words.iter().map(|word| &text[word.start..word.end]));

    let encoding = tokenizer
        .encode(pieces, true)
        .map_err(|error| GlinerXError::Inference(format!("tokenize text failed: {error}")))?;
    let input_ids = encoding
        .get_ids()
        .iter()
        .map(|&id| i64::from(id))
        .collect::<Vec<_>>();
    let attention_mask = encoding
        .get_attention_mask()
        .iter()
        .map(|&mask| i64::from(mask))
        .collect::<Vec<_>>();
    let words_mask = build_words_mask_from_word_ids(encoding.get_word_ids(), prompt_word_count);
    Ok(Some(GlinerXTextTensors {
        words,
        input_ids,
        attention_mask,
        words_mask,
    }))
}

fn words_splitter_limited(text: &str, max_words: usize) -> Vec<WordSpan> {
    let mut words = Vec::new();
    if max_words == 0 {
        return words;
    }
    let mut chars = text.char_indices().peekable();

    while let Some((pos, ch)) = chars.next() {
        if words.len() >= max_words {
            break;
        }
        if ch.is_whitespace() {
            continue;
        }

        if ch.is_alphanumeric() || ch == '_' {
            let start = pos;
            let mut end = pos + ch.len_utf8();

            while let Some(&(next_pos, next_ch)) = chars.peek() {
                if next_ch.is_alphanumeric() || next_ch == '_' {
                    end = next_pos + next_ch.len_utf8();
                    chars.next();
                } else if next_ch == '-' {
                    let mut lookahead = chars.clone();
                    lookahead.next();
                    let Some(&(after_pos, after_hyphen)) = lookahead.peek() else {
                        break;
                    };
                    if after_hyphen.is_alphanumeric() || after_hyphen == '_' {
                        chars.next();
                        chars.next();
                        end = after_pos + after_hyphen.len_utf8();
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            words.push(WordSpan { start, end });
        } else {
            words.push(WordSpan {
                start: pos,
                end: pos + ch.len_utf8(),
            });
        }
    }
    words
}

fn build_words_mask_from_word_ids(word_ids: &[Option<u32>], prompt_word_count: usize) -> Vec<i64> {
    let mut out = Vec::with_capacity(word_ids.len());
    let mut previous = None::<u32>;
    for &word_id in word_ids {
        let marker = match word_id {
            Some(current) if previous != Some(current) && current as usize >= prompt_word_count => {
                current as i64 + 1 - prompt_word_count as i64
            }
            _ => 0,
        };
        out.push(marker);
        previous = word_id;
    }
    out
}

pub(super) fn build_span_tensors(num_words: usize, max_width: usize) -> (Vec<i64>, Vec<bool>) {
    let num_spans = num_words * max_width;
    let mut span_idx = vec![0; num_spans * 2];
    let mut span_mask = vec![false; num_spans];

    for start_idx in 0..num_words {
        let actual_max_width = max_width.min(num_words - start_idx);
        for width in 0..actual_max_width {
            let dim = start_idx * max_width + width;
            span_idx[dim * 2] = start_idx as i64;
            span_idx[dim * 2 + 1] = (start_idx + width) as i64;
            span_mask[dim] = true;
        }
    }
    (span_idx, span_mask)
}

pub(super) fn extract_logits(value: &DynValue) -> Result<Vec<f32>, GlinerXError> {
    if let Ok(view) = value.try_extract_tensor::<f32>() {
        return view
            .as_slice()
            .map(ToOwned::to_owned)
            .ok_or_else(|| GlinerXError::Inference("logits f32 not contiguous".to_owned()));
    }
    let view = value
        .try_extract_tensor::<f16>()
        .map_err(|_| GlinerXError::Inference("could not extract logits".to_owned()))?;
    let slice = view
        .as_slice()
        .ok_or_else(|| GlinerXError::Inference("logits fp16 not contiguous".to_owned()))?;
    Ok(slice.iter().map(|value| value.to_f32()).collect())
}

pub(super) fn decode_predictions(
    sequence: usize,
    text: &str,
    words: &[WordSpan],
    labels: &[String],
    max_width: usize,
    threshold: f32,
    logits: &[f32],
) -> Result<Vec<GlinerXPrediction>, GlinerXError> {
    let num_words = words.len();
    let num_labels = labels.len();
    let expected_len = num_words * max_width * num_labels;
    if logits.len() < expected_len {
        return Err(GlinerXError::Inference(format!(
            "logits too short: expected {expected_len}, got {}",
            logits.len()
        )));
    }

    let threshold_logit = logit_threshold(threshold);
    let mut predictions = Vec::new();
    for start_idx in 0..num_words {
        let actual_max_width = max_width.min(num_words - start_idx);
        for width in 0..actual_max_width {
            for label_idx in 0..num_labels {
                let offset = (start_idx * max_width + width) * num_labels + label_idx;
                let logit = logits[offset];
                if logit < threshold_logit {
                    continue;
                }
                let score = sigmoid(logit);
                if score < threshold {
                    continue;
                }
                let end_idx = start_idx + width;
                let start_char = words[start_idx].start;
                let end_char = words[end_idx].end;
                predictions.push(GlinerXPrediction {
                    sequence,
                    text: text[start_char..end_char].to_owned(),
                    label: labels[label_idx].clone(),
                    score,
                    span_start: start_char,
                    span_end: end_char,
                });
            }
        }
    }
    Ok(apply_highest_score_overlap(predictions))
}

fn apply_highest_score_overlap(mut predictions: Vec<GlinerXPrediction>) -> Vec<GlinerXPrediction> {
    predictions.sort_by(cmp_score_desc);
    let mut filtered = Vec::new();
    for prediction in predictions {
        let overlaps = filtered.iter().any(|row: &GlinerXPrediction| {
            prediction.span_start < row.span_end && prediction.span_end > row.span_start
        });
        if !overlaps {
            filtered.push(prediction);
        }
    }
    filtered.sort_by(cmp_span_order);
    filtered
}

fn cmp_score_desc(left: &GlinerXPrediction, right: &GlinerXPrediction) -> Ordering {
    right
        .score
        .partial_cmp(&left.score)
        .unwrap_or(Ordering::Equal)
        .then_with(|| left.span_start.cmp(&right.span_start))
        .then_with(|| left.span_end.cmp(&right.span_end))
        .then_with(|| left.label.cmp(&right.label))
}

fn cmp_span_order(left: &GlinerXPrediction, right: &GlinerXPrediction) -> Ordering {
    left.span_start
        .cmp(&right.span_start)
        .then_with(|| left.span_end.cmp(&right.span_end))
        .then_with(|| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(Ordering::Equal)
        })
        .then_with(|| left.label.cmp(&right.label))
}

fn sigmoid(value: f32) -> f32 {
    1.0 / (1.0 + (-value).exp())
}

fn logit_threshold(threshold: f32) -> f32 {
    if threshold <= 0.0 {
        f32::NEG_INFINITY
    } else if threshold >= 1.0 {
        f32::INFINITY
    } else {
        (threshold / (1.0 - threshold)).ln()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitter_keeps_hyphenated_words_and_punctuation_offsets() {
        let text = "AI-native graph, phase-5.";
        let words = words_splitter_limited(text, usize::MAX);
        let pieces = words
            .iter()
            .map(|word| &text[word.start..word.end])
            .collect::<Vec<_>>();
        assert_eq!(pieces, vec!["AI-native", "graph", ",", "phase-5", "."]);
    }

    #[test]
    fn prompt_words_are_masked_and_text_words_start_at_one() {
        let word_ids = [
            Some(0),
            Some(1),
            Some(2),
            Some(3),
            Some(4),
            Some(5),
            Some(6),
            Some(7),
            Some(7),
            Some(8),
            None,
        ];
        let words_mask = build_words_mask_from_word_ids(&word_ids, 6);
        assert_eq!(words_mask, vec![0, 0, 0, 0, 0, 0, 1, 2, 0, 3, 0]);
    }

    #[test]
    fn span_tensors_mark_only_valid_inclusive_widths() {
        let (span_idx, span_mask) = build_span_tensors(3, 3);
        assert_eq!(
            span_idx,
            vec![0, 0, 0, 1, 0, 2, 1, 1, 1, 2, 0, 0, 2, 2, 0, 0, 0, 0]
        );
        assert_eq!(
            span_mask,
            vec![true, true, true, true, true, false, true, false, false]
        );
    }

    #[test]
    fn decoder_filters_overlaps_by_score_then_returns_text_order() {
        let text = "Ryan met Len";
        let words = words_splitter_limited(text, usize::MAX);
        let labels = vec!["person".to_owned(), "organization".to_owned()];
        let mut logits = vec![-10.0; words.len() * 2 * labels.len()];
        logits[span_offset(0, 0, 0, 2, labels.len())] = 1.0;
        logits[span_offset(0, 0, 1, 2, labels.len())] = 2.0;
        logits[span_offset(2, 0, 0, 2, labels.len())] = 3.0;

        let decoded = decode_predictions(4, text, &words, &labels, 2, 0.5, &logits).unwrap();

        assert_eq!(decoded.len(), 2);
        assert_eq!(decoded[0].sequence, 4);
        assert_eq!(decoded[0].text, "Ryan");
        assert_eq!(decoded[0].label, "organization");
        assert_eq!(decoded[1].text, "Len");
        assert_eq!(decoded[1].label, "person");
    }

    fn span_offset(
        start_idx: usize,
        width: usize,
        label_idx: usize,
        max_width: usize,
        num_labels: usize,
    ) -> usize {
        (start_idx * max_width + width) * num_labels + label_idx
    }
}
