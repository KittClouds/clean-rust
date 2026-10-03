#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ByteSpan {
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Copy, Debug)]
pub struct Utf8Cursor<'a> {
    source: &'a str,
    offset: usize,
}

impl<'a> Utf8Cursor<'a> {
    pub fn new(source: &'a str) -> Self {
        Self { source, offset: 0 }
    }

    pub fn offset(&self) -> usize {
        self.offset
    }

    pub fn next_scalar(&mut self) -> Option<(char, ByteSpan)> {
        let ch = self.source.get(self.offset..)?.chars().next()?;
        let start = self.offset;
        self.offset += ch.len_utf8();
        Some((ch, ByteSpan { start, end: self.offset }))
    }
}
