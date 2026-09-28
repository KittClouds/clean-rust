use super::*;

pub(super) struct BinaryWriter {
    writer: BufWriter<File>,
    position: u64,
    payload_hasher: blake3::Hasher,
    sections: [SectionHeader; SECTION_COUNT],
    section_index: usize,
}

impl BinaryWriter {
    pub(super) fn new(file: File) -> Result<Self, DiscoveryViewError> {
        let mut writer = BufWriter::new(file);
        writer.write_all(&vec![0_u8; BINARY_HEADER_BYTES])?;
        let mut value = Self {
            writer,
            position: BINARY_HEADER_BYTES as u64,
            payload_hasher: blake3::Hasher::new(),
            sections: [SectionHeader::default(); SECTION_COUNT],
            section_index: 0,
        };
        value.align(false)?;
        Ok(value)
    }

    pub(super) fn section<T: AsBytes>(
        &mut self,
        kind: SectionKind,
        values: &[T],
    ) -> Result<(), DiscoveryViewError> {
        self.align(true)?;
        let bytes = values.as_bytes();
        self.sections[self.section_index] =
            SectionHeader::new(kind, std::mem::size_of::<T>(), self.position, values.len());
        self.section_index += 1;
        self.writer.write_all(bytes)?;
        self.payload_hasher.update(bytes);
        self.position += bytes.len() as u64;
        Ok(())
    }

    pub(super) fn bytes(
        &mut self,
        kind: SectionKind,
        values: &[u8],
    ) -> Result<(), DiscoveryViewError> {
        self.section(kind, values)
    }

    fn align(&mut self, hash_padding: bool) -> Result<(), DiscoveryViewError> {
        let aligned = self.position.div_ceil(SECTION_ALIGNMENT) * SECTION_ALIGNMENT;
        let padding = (aligned - self.position) as usize;
        if padding > 0 {
            let zeros = [0_u8; SECTION_ALIGNMENT as usize];
            self.writer.write_all(&zeros[..padding])?;
            if hash_padding {
                self.payload_hasher.update(&zeros[..padding]);
            }
            self.position = aligned;
        }
        Ok(())
    }

    pub(super) fn finish(
        mut self,
    ) -> Result<(File, [SectionHeader; SECTION_COUNT], [u8; 32], u64), DiscoveryViewError> {
        if self.section_index != SECTION_COUNT {
            return Err(DiscoveryViewError::Invalid(format!(
                "wrote {} discovery sections, expected {SECTION_COUNT}",
                self.section_index
            )));
        }
        self.writer.flush()?;
        let digest = *self.payload_hasher.finalize().as_bytes();
        let file = self
            .writer
            .into_inner()
            .map_err(|error| error.into_error())?;
        Ok((file, self.sections, digest, self.position))
    }
}
