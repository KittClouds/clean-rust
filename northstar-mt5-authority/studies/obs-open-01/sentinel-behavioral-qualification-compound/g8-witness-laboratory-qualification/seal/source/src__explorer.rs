use crate::model::{
    AuthorityVerdict, CoverageReceipt, FrozenComparison, LabArtifactClass, SearchResult,
    SearchStatus, SeparatorCertificate,
};
use crate::ranking::{finite_shell, rank_key};
use crate::verifier::{coverage_accumulator, domain_id, make_certificate, verify_separator};

pub fn canonical_first(comparison: &FrozenComparison, max_shell: u8) -> SearchResult {
    let words = finite_shell(max_shell);
    for (index, word) in words.into_iter().enumerate() {
        let Ok(certificate) = make_certificate(comparison.clone(), word, "canonical rank search")
        else {
            continue;
        };
        if verify_separator(&certificate).accepted {
            return SearchResult {
                search_status: SearchStatus::Complete,
                authority_verdict: AuthorityVerdict::BehaviorallyNonEquivalentWithVerifiedSeparator,
                artifact_class: LabArtifactClass::CanonicalFirstWitness,
                certificate: Some(certificate),
                dispositioned_lower_ranks: index,
            };
        }
    }
    SearchResult {
        search_status: SearchStatus::BoundedDomainExhausted,
        authority_verdict: AuthorityVerdict::Unknown,
        artifact_class: LabArtifactClass::OtherRegisteredArtifact,
        certificate: None,
        dispositioned_lower_ranks: 0,
    }
}

pub fn bounded_coverage(
    comparison: &FrozenComparison,
    max_shell: u8,
) -> (SearchResult, CoverageReceipt) {
    let words = finite_shell(max_shell);
    let mut accepted = Vec::new();
    let mut visited = Vec::with_capacity(words.len());
    for (index, word) in words.iter().enumerate() {
        visited.push(index);
        let Ok(certificate) =
            make_certificate(comparison.clone(), word.clone(), "bounded coverage")
        else {
            continue;
        };
        if verify_separator(&certificate).accepted {
            accepted.push(index);
        }
    }
    let receipt = CoverageReceipt {
        domain_id: domain_id(&words),
        domain_cardinality: words.len(),
        visited_accumulator_hash: coverage_accumulator(&visited),
        visited_indices: visited,
        accepted_separator_indices: accepted.clone(),
    };
    let result = SearchResult {
        search_status: SearchStatus::BoundedDomainExhausted,
        authority_verdict: AuthorityVerdict::Unknown,
        artifact_class: LabArtifactClass::OtherRegisteredArtifact,
        certificate: None,
        dispositioned_lower_ranks: words.len(),
    };
    (result, receipt)
}

pub fn shrink_by_deletion(certificate: &SeparatorCertificate) -> SearchResult {
    let mut current = certificate.clone();
    let mut changed = false;
    loop {
        let parent_rank = rank_key(&current.neutral_token_sequence);
        let mut accepted_child = None;
        for index in 0..current.neutral_token_sequence.len() {
            let mut child_word = current.neutral_token_sequence.clone();
            child_word.remove(index);
            if rank_key(&child_word) >= parent_rank {
                continue;
            }
            let Ok(child) =
                make_certificate(current.comparison.clone(), child_word, "deletion shrink")
            else {
                continue;
            };
            if verify_separator(&child).accepted {
                accepted_child = Some(child);
                break;
            }
        }
        match accepted_child {
            Some(child) => {
                current = child;
                changed = true;
            }
            None => break,
        }
    }
    SearchResult {
        search_status: SearchStatus::Complete,
        authority_verdict: AuthorityVerdict::BehaviorallyNonEquivalentWithVerifiedSeparator,
        artifact_class: if changed {
            LabArtifactClass::ShrunkWitness
        } else {
            LabArtifactClass::OtherRegisteredArtifact
        },
        certificate: Some(current),
        dispositioned_lower_ranks: 0,
    }
}
