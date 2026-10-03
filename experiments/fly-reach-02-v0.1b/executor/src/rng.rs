#[derive(Clone, Copy, Debug)]
pub struct Rng(pub u64);

impl Rng {
    #[inline]
    pub fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^ (z >> 31)
    }

    #[inline]
    pub fn index(&mut self, n: usize) -> usize {
        assert!(n > 0);
        let bound = n as u64;
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let x = self.next();
            if x >= threshold {
                return (x % bound) as usize;
            }
        }
    }

    #[inline]
    pub fn unit(&mut self) -> f32 {
        ((self.next() >> 40) as f32) / 16_777_216.0
    }

    pub fn shuffle<T>(&mut self, values: &mut [T]) {
        for i in (1..values.len()).rev() {
            let j = self.index(i + 1);
            values.swap(i, j);
        }
    }
}
