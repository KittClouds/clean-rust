use std::io::Write;

use hashbrown::HashMap;
use rdc_experiment_004::Choice;

use crate::{episodes::Episode, evaluation::EvalLabel, inspection::SourceStateStore};

#[derive(Clone, Copy, Debug, Default)]
pub struct DomainEstimate {
    pub examples: u32,
    pub wrong_to_right: u32,
    pub right_to_wrong: u32,
}

impl DomainEstimate {
    pub fn expected_benefit_milli(self) -> i32 {
        if self.examples == 0 {
            return 0;
        }
        let net = self.wrong_to_right as i32 - self.right_to_wrong as i32;
        net * 1000 / self.examples as i32
    }
}

/// Frozen development-set lookup table estimating net completion change per inspection.
#[derive(Clone, Debug)]
pub struct DevelopmentValueModel {
    domains: [DomainEstimate; 8],
}

impl DevelopmentValueModel {
    pub fn fit(
        episodes: &[Episode],
        labels: &[EvalLabel],
        source_state: &SourceStateStore,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        if episodes.len() != labels.len() {
            return Err("development episode and label counts differ".into());
        }
        let label_by_id = labels
            .iter()
            .map(|label| (label.episode_id, label.correct_action))
            .collect::<HashMap<_, _>>();
        let mut domains = [DomainEstimate::default(); 8];
        for episode in episodes {
            let correct = *label_by_id
                .get(&episode.id)
                .ok_or("development label missing")?;
            let source = source_state
                .get(episode.id)
                .ok_or("development inspection source missing")?;
            let active = episode.frame.features.primary_action;
            let inspected = if source.signature_valid {
                Choice::from_code(source.recommendation).unwrap_or(active)
            } else {
                active
            };
            let estimate = &mut domains[episode.frame.inspection_domain as usize];
            estimate.examples += 1;
            if active != correct && inspected == correct {
                estimate.wrong_to_right += 1;
            } else if active == correct && inspected != correct {
                estimate.right_to_wrong += 1;
            }
        }
        Ok(Self { domains })
    }

    pub fn estimate(&self, domain: u8) -> DomainEstimate {
        self.domains[domain as usize]
    }

    pub fn score(&self, domain: u8) -> i32 {
        self.estimate(domain).expected_benefit_milli()
    }

    pub fn write_csv(
        &self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = std::io::BufWriter::new(std::fs::File::create(path)?);
        writeln!(
            writer,
            "inspection_domain,development_examples,wrong_to_right,right_to_wrong,expected_net_benefit_milli"
        )?;
        for (domain, estimate) in self.domains.iter().enumerate() {
            writeln!(
                writer,
                "{domain},{},{},{},{}",
                estimate.examples,
                estimate.wrong_to_right,
                estimate.right_to_wrong,
                estimate.expected_benefit_milli()
            )?;
        }
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}
