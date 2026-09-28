use bytes::Buf;

pub fn byte_at_task_cursor(input: &[u8]) -> u8 {
    let mut cursor = input;
    cursor.advance(0);
    cursor.get_u8()
}
