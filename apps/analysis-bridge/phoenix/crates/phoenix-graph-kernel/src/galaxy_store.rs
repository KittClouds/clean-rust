use crate::galaxy_store_format::{
    GalaxyPageHeader, GalaxyPageManifest, GalaxyStoreManifest, GALAXY_PAGE_HEADER_BYTES,
    GALAXY_PAGE_MAGIC, GALAXY_STORE_SCHEMA_VERSION,
};
use hashbrown::HashMap;
use memmap2::{Mmap, MmapOptions};
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::fs::File;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use xxhash_rust::xxh3::xxh3_64;
use zerocopy::{FromBytes, Ref};

#[derive(Debug)]
pub enum GalaxyStoreError {
    Io(std::io::Error),
    Json(serde_json::Error),
    Invalid(String),
}

impl Display for GalaxyStoreError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "galaxy store I/O error: {error}"),
            Self::Json(error) => write!(formatter, "galaxy store manifest error: {error}"),
            Self::Invalid(message) => write!(formatter, "invalid galaxy store: {message}"),
        }
    }
}

impl Error for GalaxyStoreError {}

impl From<std::io::Error> for GalaxyStoreError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<serde_json::Error> for GalaxyStoreError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

pub struct GalaxyMappedPage {
    manifest: GalaxyPageManifest,
    map: Mmap,
}

impl GalaxyMappedPage {
    pub fn manifest(&self) -> &GalaxyPageManifest {
        &self.manifest
    }

    pub fn header(&self) -> Result<GalaxyPageHeader, GalaxyStoreError> {
        Ref::<_, GalaxyPageHeader>::new(self.map.get(..GALAXY_PAGE_HEADER_BYTES).ok_or_else(
            || GalaxyStoreError::Invalid(format!("short page {}", self.manifest.file)),
        )?)
        .map(|header| *header)
        .ok_or_else(|| {
            GalaxyStoreError::Invalid(format!("unaligned page header {}", self.manifest.file))
        })
    }

    pub fn payload(&self) -> &[u8] {
        &self.map[GALAXY_PAGE_HEADER_BYTES..]
    }

    pub fn records<T: FromBytes>(&self) -> Result<Ref<&[u8], [T]>, GalaxyStoreError> {
        let header = self.header()?;
        if header.record_size as usize != size_of::<T>() {
            return Err(GalaxyStoreError::Invalid(format!(
                "record width mismatch in {}: {} != {}",
                self.manifest.file,
                header.record_size,
                size_of::<T>()
            )));
        }
        Ref::<_, [T]>::new_slice(self.payload()).ok_or_else(|| {
            GalaxyStoreError::Invalid(format!("record layout mismatch in {}", self.manifest.file))
        })
    }
}

pub struct GalaxyGraphStore {
    root: PathBuf,
    manifest: GalaxyStoreManifest,
    pages: HashMap<String, GalaxyMappedPage>,
}

impl GalaxyGraphStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, GalaxyStoreError> {
        let root = root.as_ref().to_path_buf();
        let manifest_bytes = std::fs::read(root.join("manifest.json"))?;
        let manifest: GalaxyStoreManifest = serde_json::from_slice(&manifest_bytes)?;
        if manifest.schema_version != GALAXY_STORE_SCHEMA_VERSION {
            return Err(GalaxyStoreError::Invalid(format!(
                "unsupported schema {}",
                manifest.schema_version
            )));
        }
        let mut pages = HashMap::with_capacity(manifest.pages.len());
        for page_manifest in &manifest.pages {
            let file = File::open(root.join(&page_manifest.file))?;
            let map = unsafe { MmapOptions::new().map(&file)? };
            let page = GalaxyMappedPage {
                manifest: page_manifest.clone(),
                map,
            };
            validate_page(&page, manifest.generation_hash)?;
            pages.insert(page_manifest.file.clone(), page);
        }
        Ok(Self {
            root,
            manifest,
            pages,
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn manifest(&self) -> &GalaxyStoreManifest {
        &self.manifest
    }

    pub fn page(&self, file: &str) -> Result<&GalaxyMappedPage, GalaxyStoreError> {
        self.pages
            .get(file)
            .ok_or_else(|| GalaxyStoreError::Invalid(format!("missing page {file}")))
    }

    pub fn page_for(
        &self,
        page_kind: u16,
        manifold: Option<crate::GalaxyManifoldKind>,
        lod: u16,
    ) -> Result<&GalaxyMappedPage, GalaxyStoreError> {
        let page = self.manifest.pages.iter().find(|page| {
            page.page_kind == page_kind && page.manifold == manifold && page.lod == lod
        });
        self.page(
            &page
                .ok_or_else(|| GalaxyStoreError::Invalid("page contract not found".to_owned()))?
                .file,
        )
    }
}

fn validate_page(page: &GalaxyMappedPage, generation_hash: u64) -> Result<(), GalaxyStoreError> {
    let header = page.header()?;
    if header.magic != GALAXY_PAGE_MAGIC
        || header.schema_version != GALAXY_STORE_SCHEMA_VERSION
        || header.generation_hash != generation_hash
        || header.page_kind != page.manifest.page_kind
        || header.record_size != page.manifest.record_size
        || header.record_count != page.manifest.record_count
        || header.content_hash != page.manifest.content_hash
    {
        return Err(GalaxyStoreError::Invalid(format!(
            "header mismatch in {}",
            page.manifest.file
        )));
    }
    let expected_len = (header.record_count as usize)
        .checked_mul(header.record_size as usize)
        .and_then(|payload| payload.checked_add(GALAXY_PAGE_HEADER_BYTES))
        .ok_or_else(|| GalaxyStoreError::Invalid("page length overflow".to_owned()))?;
    if page.map.len() != expected_len || xxh3_64(page.payload()) != header.content_hash {
        return Err(GalaxyStoreError::Invalid(format!(
            "content mismatch in {}",
            page.manifest.file
        )));
    }
    Ok(())
}
