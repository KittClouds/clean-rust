//! The narrow embedding interface the Library depends on.
//!
//! Implementations are per model family (a fixed descriptor, specialised pipeline), not a
//! generic loader. Output is one contiguous row-major matrix of L2-normalised `f32` rows.

/// Which side of retrieval an input is embedded for; families prompt the two differently.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Role {
    Query,
    Document,
}

#[derive(Debug, Clone, Copy)]
pub struct Input<'a> {
    pub role: Role,
    pub text: &'a str,
}

impl<'a> Input<'a> {
    pub fn query(text: &'a str) -> Self {
        Input {
            role: Role::Query,
            text,
        }
    }

    pub fn document(text: &'a str) -> Self {
        Input {
            role: Role::Document,
            text,
        }
    }
}

/// `rows × dims` row-major vectors.
#[derive(Debug, Clone, PartialEq)]
pub struct Embeddings {
    values: Vec<f32>,
    dims: usize,
}

impl Embeddings {
    pub fn new(values: Vec<f32>, dims: usize) -> Result<Self, String> {
        if dims == 0 || !values.len().is_multiple_of(dims) {
            return Err(format!(
                "embedding matrix of {} values is not a multiple of {dims} dimensions",
                values.len()
            ));
        }
        Ok(Embeddings { values, dims })
    }

    pub fn from_rows(rows: Vec<Vec<f32>>, dims: usize) -> Result<Self, String> {
        if rows.iter().any(|r| r.len() != dims) {
            return Err(format!(
                "embedder returned a row that is not {dims}-dimensional"
            ));
        }
        Embeddings::new(rows.concat(), dims)
    }

    pub fn rows(&self) -> usize {
        self.values.len() / self.dims
    }

    pub fn dims(&self) -> usize {
        self.dims
    }

    pub fn row(&self, index: usize) -> &[f32] {
        &self.values[index * self.dims..(index + 1) * self.dims]
    }

    pub fn values(&self) -> &[f32] {
        &self.values
    }

    pub fn iter(&self) -> impl Iterator<Item = &[f32]> {
        self.values.chunks_exact(self.dims)
    }
}

/// What produced a vector space. `id` is the string stored on every memory record; two
/// embedders with different ids never share a vector channel.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModelIdentity {
    pub id: String,
    pub family: String,
    pub dims: usize,
}

pub trait Embedder: Send + Sync {
    fn embed(&self, batch: &[Input<'_>]) -> Result<Embeddings, String>;
    fn dimension(&self) -> usize;
    fn model_identity(&self) -> &ModelIdentity;

    /// Embeds one input and returns its row.
    fn embed_one(&self, input: Input<'_>) -> Result<Vec<f32>, String> {
        let out = self.embed(&[input])?;
        if out.rows() != 1 {
            return Err("embedder returned no vector".into());
        }
        Ok(out.row(0).to_vec())
    }
}
