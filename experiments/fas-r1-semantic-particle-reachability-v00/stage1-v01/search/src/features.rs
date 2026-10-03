use r1_world::InferenceTask;

/// Dense, immutable view of the frozen sensor output and public incidence.
///
/// constraint_embeddings is row-major [clauses, hidden_dim]; incidence arrays
/// are row-major [clauses, entities] and [clauses, roles]. The adapter that
/// loads .npy extraction files should build this once per task.
#[derive(Clone, Debug, PartialEq)]
pub struct SemanticFeatures {
    pub hidden_dim: usize,
    pub constraint_count: usize,
    pub entity_count: usize,
    pub role_count: usize,
    pub constraint_embeddings: Box<[f32]>,
    pub global_embedding: Box<[f32]>,
    pub constraint_mask: Box<[u8]>,
    pub entity_incidence: Box<[u8]>,
    pub role_incidence: Box<[u8]>,
    pub entity_mask: Box<[u8]>,
    pub role_mask: Box<[u8]>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureError(pub String);

impl std::fmt::Display for FeatureError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for FeatureError {}

impl SemanticFeatures {
    pub fn validate_for(&self, task: &InferenceTask) -> Result<(), FeatureError> {
        let expected_entities = usize::from(task.n);
        let expected_roles = usize::from(task.k);
        let expected = [
            (self.hidden_dim > 0, "hidden_dim must be positive"),
            (
                self.constraint_count == task.clauses.len(),
                "constraint count does not match the inference projection",
            ),
            (
                self.entity_count == expected_entities,
                "entity count does not match the inference projection",
            ),
            (
                self.role_count == expected_roles,
                "role count does not match the inference projection",
            ),
            (
                self.constraint_embeddings.len() == self.constraint_count * self.hidden_dim,
                "constraint embedding storage has the wrong length",
            ),
            (
                self.global_embedding.len() == self.hidden_dim,
                "global embedding has the wrong length",
            ),
            (
                self.constraint_mask.len() == self.constraint_count,
                "constraint mask has the wrong length",
            ),
            (
                self.entity_incidence.len() == self.constraint_count * self.entity_count,
                "entity incidence has the wrong length",
            ),
            (
                self.role_incidence.len() == self.constraint_count * self.role_count,
                "role incidence has the wrong length",
            ),
            (
                self.entity_mask.len() == self.entity_count,
                "entity mask has the wrong length",
            ),
            (
                self.role_mask.len() == self.role_count,
                "role mask has the wrong length",
            ),
        ];
        if let Some((_, message)) = expected.iter().find(|(valid, _)| !valid) {
            return Err(FeatureError((*message).to_owned()));
        }
        if task.entity_mentions.len() != self.constraint_count
            || task.role_mentions.len() != self.constraint_count
        {
            return Err(FeatureError(
                "public incidence rows do not align with the clause list".to_owned(),
            ));
        }
        Ok(())
    }

    /// Construct public incidence directly from the rendered projection.
    /// Embeddings are supplied by the frozen extraction adapter.
    pub fn from_projection(
        task: &InferenceTask,
        hidden_dim: usize,
        constraint_embeddings: Box<[f32]>,
        global_embedding: Box<[f32]>,
    ) -> Result<Self, FeatureError> {
        let clauses = task.clauses.len();
        let entities = usize::from(task.n);
        let roles = usize::from(task.k);
        let mut entity_incidence = vec![0u8; clauses * entities].into_boxed_slice();
        let mut role_incidence = vec![0u8; clauses * roles].into_boxed_slice();
        for clause in 0..clauses {
            for &entity in &task.entity_mentions[clause] {
                if usize::from(entity) < entities {
                    entity_incidence[clause * entities + usize::from(entity)] = 1;
                }
            }
            for &role in &task.role_mentions[clause] {
                if usize::from(role) < roles {
                    role_incidence[clause * roles + usize::from(role)] = 1;
                }
            }
        }
        let result = Self {
            hidden_dim,
            constraint_count: clauses,
            entity_count: entities,
            role_count: roles,
            constraint_embeddings,
            global_embedding,
            constraint_mask: vec![1u8; clauses].into_boxed_slice(),
            entity_incidence,
            role_incidence,
            entity_mask: vec![1u8; entities].into_boxed_slice(),
            role_mask: vec![1u8; roles].into_boxed_slice(),
        };
        result.validate_for(task)?;
        Ok(result)
    }
}
