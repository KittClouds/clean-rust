pub(crate) fn checked_product(left: usize, right: usize, label: &str) -> Result<usize, String> {
    left.checked_mul(right)
        .ok_or_else(|| format!("packed vector {label} overflow"))
}

pub(crate) fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, String> {
    Ok(u16::from_le_bytes(read_array(bytes, offset)?))
}

pub(crate) fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, String> {
    Ok(u32::from_le_bytes(read_array(bytes, offset)?))
}

pub(crate) fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, String> {
    Ok(u64::from_le_bytes(read_array(bytes, offset)?))
}

pub(crate) fn read_f64(bytes: &[u8], offset: usize) -> Result<f64, String> {
    Ok(f64::from_le_bytes(read_array(bytes, offset)?))
}

pub(crate) fn read_u32_page(bytes: &[u8]) -> Vec<u32> {
    bytes
        .chunks_exact(4)
        .map(|word| u32::from_le_bytes(word.try_into().unwrap()))
        .collect()
}

pub(crate) fn write_u16(bytes: &mut [u8], offset: usize, value: u16) {
    bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

pub(crate) fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

pub(crate) fn write_u64(bytes: &mut [u8], offset: usize, value: u64) {
    bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

fn read_array<const N: usize>(bytes: &[u8], offset: usize) -> Result<[u8; N], String> {
    bytes
        .get(offset..offset + N)
        .ok_or_else(|| "packed vector header is truncated".to_string())?
        .try_into()
        .map_err(|_| "packed vector header width drift".to_string())
}
