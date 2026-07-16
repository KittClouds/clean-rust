use crate::LinkPredictionError;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct TgbConflictEntry {
    pub observed_at: i64,
    pub source: u32,
    pub relation: u32,
    pub destinations: Vec<u32>,
}

#[derive(Clone, Debug)]
enum Global {
    Scalar,
    Dtype,
    FromBuffer,
}

#[derive(Clone, Debug)]
enum Value {
    Dict(Vec<TgbConflictEntry>),
    Mark,
    Str(String),
    Bytes(Vec<u8>),
    Int(i64),
    Bool(bool),
    None,
    Tuple(Vec<Value>),
    Global(Global),
    DtypeI64,
    Scalar(i64),
    Array(Vec<u32>),
}

pub(crate) fn parse_tgb_conflict_pickle(
    bytes: &[u8],
) -> Result<Vec<TgbConflictEntry>, LinkPredictionError> {
    PickleParser::new(bytes).parse()
}

struct PickleParser<'a> {
    bytes: &'a [u8],
    cursor: usize,
    stack: Vec<Value>,
    memo: [Option<Value>; 28],
    memo_index: usize,
}

impl<'a> PickleParser<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self {
            bytes,
            cursor: 0,
            stack: Vec::with_capacity(32),
            memo: std::array::from_fn(|_| None),
            memo_index: 0,
        }
    }

    fn parse(mut self) -> Result<Vec<TgbConflictEntry>, LinkPredictionError> {
        loop {
            let opcode = self.byte()?;
            match opcode {
                0x80 => {
                    if self.byte()? != 5 {
                        return Err(LinkPredictionError::InvalidPickle("protocol"));
                    }
                }
                0x95 => {
                    let frame = self.u64()? as usize;
                    if frame > self.bytes.len().saturating_sub(self.cursor) {
                        return Err(LinkPredictionError::InvalidPickle("frame"));
                    }
                }
                b'}' => self.stack.push(Value::Dict(Vec::new())),
                0x94 => self.memoize()?,
                b'(' => self.stack.push(Value::Mark),
                0x8c => {
                    let len = self.byte()? as usize;
                    let value = std::str::from_utf8(self.take(len)?)
                        .map_err(|_| LinkPredictionError::InvalidPickle("unicode"))?;
                    self.stack.push(Value::Str(value.to_owned()));
                }
                0x93 => self.stack_global()?,
                0x89 => self.stack.push(Value::Bool(false)),
                0x88 => self.stack.push(Value::Bool(true)),
                0x87 => self.fixed_tuple(3)?,
                b'R' => self.reduce()?,
                b'K' => {
                    let value = self.byte()?;
                    self.stack.push(Value::Int(i64::from(value)));
                }
                b'M' => {
                    let value = self.u16()?;
                    self.stack.push(Value::Int(i64::from(value)));
                }
                b'J' => {
                    let value = i32::from_le_bytes(self.array()?);
                    self.stack.push(Value::Int(i64::from(value)));
                }
                b'N' => self.stack.push(Value::None),
                b't' => self.mark_tuple()?,
                b'b' => self.build()?,
                b'C' => {
                    let len = self.byte()? as usize;
                    let value = self.take(len)?.to_vec();
                    self.stack.push(Value::Bytes(value));
                }
                0x86 => self.fixed_tuple(2)?,
                b'h' => {
                    let index = self.byte()? as usize;
                    self.memo_get(index)?;
                }
                b'j' => {
                    let index = self.u32()? as usize;
                    self.memo_get(index)?;
                }
                0x96 => {
                    let len = usize::try_from(self.u64()?)
                        .map_err(|_| LinkPredictionError::InvalidPickle("bytearray"))?;
                    let value = self.take(len)?.to_vec();
                    self.stack.push(Value::Bytes(value));
                }
                0x85 => self.fixed_tuple(1)?,
                b'u' => self.set_items()?,
                b'.' => return self.finish(),
                other => return Err(LinkPredictionError::UnsupportedPickleOpcode(other)),
            }
        }
    }

    fn memoize(&mut self) -> Result<(), LinkPredictionError> {
        if self.memo_index < self.memo.len() {
            self.memo[self.memo_index] = Some(
                self.stack
                    .last()
                    .ok_or(LinkPredictionError::InvalidPickle("memo stack"))?
                    .clone(),
            );
        }
        self.memo_index += 1;
        Ok(())
    }

    fn memo_get(&mut self, index: usize) -> Result<(), LinkPredictionError> {
        let value = self
            .memo
            .get(index)
            .and_then(Option::as_ref)
            .ok_or(LinkPredictionError::InvalidPickle("memo reference"))?
            .clone();
        self.stack.push(value);
        Ok(())
    }

    fn stack_global(&mut self) -> Result<(), LinkPredictionError> {
        let name = self.pop_string()?;
        let module = self.pop_string()?;
        let global = match (module.as_str(), name.as_str()) {
            ("numpy.core.multiarray", "scalar") => Global::Scalar,
            ("numpy", "dtype") => Global::Dtype,
            ("numpy.core.numeric", "_frombuffer") => Global::FromBuffer,
            _ => return Err(LinkPredictionError::InvalidPickle("global")),
        };
        self.stack.push(Value::Global(global));
        Ok(())
    }

    fn reduce(&mut self) -> Result<(), LinkPredictionError> {
        let args = match self.pop()? {
            Value::Tuple(values) => values,
            _ => return Err(LinkPredictionError::InvalidPickle("reduce args")),
        };
        let callable = match self.pop()? {
            Value::Global(value) => value,
            _ => return Err(LinkPredictionError::InvalidPickle("reduce callable")),
        };
        let value = match callable {
            Global::Dtype => parse_dtype(args)?,
            Global::Scalar => parse_scalar(args)?,
            Global::FromBuffer => parse_array(args)?,
        };
        self.stack.push(value);
        Ok(())
    }

    fn build(&mut self) -> Result<(), LinkPredictionError> {
        let _state = self.pop()?;
        let value = self.pop()?;
        if !matches!(value, Value::DtypeI64) {
            return Err(LinkPredictionError::InvalidPickle("build target"));
        }
        self.stack.push(value);
        Ok(())
    }

    fn fixed_tuple(&mut self, count: usize) -> Result<(), LinkPredictionError> {
        if self.stack.len() < count {
            return Err(LinkPredictionError::InvalidPickle("tuple stack"));
        }
        let values = self.stack.split_off(self.stack.len() - count);
        self.stack.push(Value::Tuple(values));
        Ok(())
    }

    fn mark_tuple(&mut self) -> Result<(), LinkPredictionError> {
        let values = self.after_mark()?;
        self.stack.push(Value::Tuple(values));
        Ok(())
    }

    fn set_items(&mut self) -> Result<(), LinkPredictionError> {
        let values = self.after_mark()?;
        if values.len() % 2 != 0 {
            return Err(LinkPredictionError::InvalidPickle("dict items"));
        }
        let dict = self
            .stack
            .last_mut()
            .ok_or(LinkPredictionError::InvalidPickle("dict stack"))?;
        let Value::Dict(entries) = dict else {
            return Err(LinkPredictionError::InvalidPickle("dict target"));
        };
        let mut values = values.into_iter();
        while let (Some(key), Some(value)) = (values.next(), values.next()) {
            entries.push(parse_entry(key, value)?);
        }
        Ok(())
    }

    fn after_mark(&mut self) -> Result<Vec<Value>, LinkPredictionError> {
        let mark = self
            .stack
            .iter()
            .rposition(|value| matches!(value, Value::Mark))
            .ok_or(LinkPredictionError::InvalidPickle("mark"))?;
        let values = self.stack.split_off(mark + 1);
        self.stack.pop();
        Ok(values)
    }

    fn finish(mut self) -> Result<Vec<TgbConflictEntry>, LinkPredictionError> {
        if self.cursor != self.bytes.len() || self.stack.len() != 1 {
            return Err(LinkPredictionError::InvalidPickle("stop"));
        }
        match self.stack.pop() {
            Some(Value::Dict(entries)) => Ok(entries),
            _ => Err(LinkPredictionError::InvalidPickle("root")),
        }
    }

    fn pop(&mut self) -> Result<Value, LinkPredictionError> {
        self.stack
            .pop()
            .ok_or(LinkPredictionError::InvalidPickle("stack underflow"))
    }

    fn pop_string(&mut self) -> Result<String, LinkPredictionError> {
        match self.pop()? {
            Value::Str(value) => Ok(value),
            _ => Err(LinkPredictionError::InvalidPickle("string")),
        }
    }

    fn byte(&mut self) -> Result<u8, LinkPredictionError> {
        let byte = *self
            .bytes
            .get(self.cursor)
            .ok_or(LinkPredictionError::InvalidPickle("unexpected end"))?;
        self.cursor += 1;
        Ok(byte)
    }

    fn take(&mut self, len: usize) -> Result<&'a [u8], LinkPredictionError> {
        let end = self
            .cursor
            .checked_add(len)
            .ok_or(LinkPredictionError::InvalidPickle("length"))?;
        let bytes = self
            .bytes
            .get(self.cursor..end)
            .ok_or(LinkPredictionError::InvalidPickle("unexpected end"))?;
        self.cursor = end;
        Ok(bytes)
    }

    fn array<const N: usize>(&mut self) -> Result<[u8; N], LinkPredictionError> {
        self.take(N)?
            .try_into()
            .map_err(|_| LinkPredictionError::InvalidPickle("integer"))
    }

    fn u16(&mut self) -> Result<u16, LinkPredictionError> {
        Ok(u16::from_le_bytes(self.array()?))
    }

    fn u32(&mut self) -> Result<u32, LinkPredictionError> {
        Ok(u32::from_le_bytes(self.array()?))
    }

    fn u64(&mut self) -> Result<u64, LinkPredictionError> {
        Ok(u64::from_le_bytes(self.array()?))
    }
}

fn parse_dtype(args: Vec<Value>) -> Result<Value, LinkPredictionError> {
    if matches!(args.as_slice(), [Value::Str(code), Value::Bool(false), Value::Bool(true)] if code == "i8")
    {
        Ok(Value::DtypeI64)
    } else {
        Err(LinkPredictionError::InvalidPickle("dtype"))
    }
}

fn parse_scalar(args: Vec<Value>) -> Result<Value, LinkPredictionError> {
    let [Value::DtypeI64, Value::Bytes(bytes)] = args.as_slice() else {
        return Err(LinkPredictionError::InvalidPickle("scalar"));
    };
    let raw: [u8; 8] = bytes
        .as_slice()
        .try_into()
        .map_err(|_| LinkPredictionError::InvalidPickle("scalar bytes"))?;
    Ok(Value::Scalar(i64::from_le_bytes(raw)))
}

fn parse_array(args: Vec<Value>) -> Result<Value, LinkPredictionError> {
    let [Value::Bytes(bytes), Value::DtypeI64, Value::Tuple(shape), Value::Str(order)] =
        args.as_slice()
    else {
        return Err(LinkPredictionError::InvalidPickle("array"));
    };
    let [Value::Int(len)] = shape.as_slice() else {
        return Err(LinkPredictionError::InvalidPickle("array shape"));
    };
    if *len < 0 || order != "C" || bytes.len() != *len as usize * 8 {
        return Err(LinkPredictionError::InvalidPickle("array layout"));
    }
    let mut output = Vec::with_capacity(*len as usize);
    for raw in bytes.chunks_exact(8) {
        let value = i64::from_le_bytes(raw.try_into().expect("exact chunk"));
        output.push(
            u32::try_from(value).map_err(|_| LinkPredictionError::InvalidPickle("array value"))?,
        );
    }
    Ok(Value::Array(output))
}

fn parse_entry(key: Value, value: Value) -> Result<TgbConflictEntry, LinkPredictionError> {
    let Value::Tuple(key) = key else {
        return Err(LinkPredictionError::InvalidPickle("query key"));
    };
    let [Value::Scalar(observed_at), Value::Scalar(source), Value::Scalar(relation)] =
        key.as_slice()
    else {
        return Err(LinkPredictionError::InvalidPickle("query tuple"));
    };
    let Value::Array(destinations) = value else {
        return Err(LinkPredictionError::InvalidPickle("query conflicts"));
    };
    Ok(TgbConflictEntry {
        observed_at: *observed_at,
        source: u32::try_from(*source)
            .map_err(|_| LinkPredictionError::InvalidPickle("query source"))?,
        relation: u32::try_from(*relation)
            .map_err(|_| LinkPredictionError::InvalidPickle("query relation"))?,
        destinations,
    })
}
