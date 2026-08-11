use crate::{BlockLocalTopKConfig, Result, TurboQuantError};

/// Service-level objective used to divide a fixed CPU budget between queries.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SearchThroughputMode {
    /// Give one query the useful scan parallelism and minimize its latency.
    LowestLatency,
    /// Preserve substantial per-query parallelism while admitting several queries.
    Balanced,
    /// Favor completed queries per second, accepting a higher tail latency.
    MaximumThroughput,
}

/// An allocation-free scheduling recommendation for independent search requests.
///
/// `concurrent_queries` is the number of query lanes. Each lane owns its query
/// scratch and output buffer. `workers_per_query` is the size of that lane's
/// persistent worker team; worker pools must not be constructed per request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SearchThroughputPlan {
    pub concurrent_queries: usize,
    pub workers_per_query: usize,
}

/// Complete serving geometry, including the measured packed-block batch path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SearchDispatchPlan {
    /// Independent requests, each with its own persistent worker team.
    Independent(SearchThroughputPlan),
    /// One worker team traverses every block once for several admitted queries.
    PackedBatch {
        batch_queries: usize,
        workers: usize,
    },
    /// One query uses cache-block score scratch and exact fixed local top-k.
    BlockLocalTopK {
        batch_queries: usize,
        workers: usize,
        config: BlockLocalTopKConfig,
    },
}

impl SearchThroughputPlan {
    #[must_use]
    pub const fn total_worker_threads(self) -> usize {
        self.concurrent_queries * self.workers_per_query
    }
}

/// Recommend a starting team geometry within `logical_threads`.
///
/// This policy encodes the measured Ryzen 7 5800X3D crossover envelope for the
/// clean-room 768-dimensional kernels. It is deliberately a small, overridable
/// policy rather than a hidden executor. Production should re-freeze it for its
/// CPU, corpus dimensions, and traffic distribution.
pub fn recommend_search_throughput(
    bits: u8,
    rows: usize,
    logical_threads: usize,
    mode: SearchThroughputMode,
) -> Result<SearchThroughputPlan> {
    if !matches!(bits, 2 | 4) {
        return Err(TurboQuantError::UnsupportedBitWidth(bits));
    }

    // A zero value can arise from constrained containers. Keeping one usable
    // lane makes the recommendation total without creating an invalid pool.
    let threads = logical_threads.max(1);
    let plan = match mode {
        SearchThroughputMode::LowestLatency => {
            // Below 64K rows, coordination overtakes useful scan work before all
            // 16 hardware threads are occupied. Four-bit rows carry twice the
            // decode work and sustain a larger team.
            let useful_workers = if rows < 65_536 {
                if bits == 2 {
                    4
                } else {
                    8
                }
            } else {
                threads
            };
            SearchThroughputPlan {
                concurrent_queries: 1,
                workers_per_query: useful_workers.min(threads),
            }
        }
        SearchThroughputMode::Balanced => {
            let concurrent_queries = threads.min(4);
            SearchThroughputPlan {
                concurrent_queries,
                workers_per_query: (threads / concurrent_queries).max(1),
            }
        }
        SearchThroughputMode::MaximumThroughput if bits == 2 => SearchThroughputPlan {
            concurrent_queries: threads,
            workers_per_query: 1,
        },
        SearchThroughputMode::MaximumThroughput => {
            // Four-bit decoding remains compute-heavy enough for two workers per
            // request. Eight 2-worker lanes had the highest three-run median on
            // the measured 16-thread host, though the winner varied by run.
            let workers_per_query = threads.min(2);
            SearchThroughputPlan {
                concurrent_queries: (threads / workers_per_query).max(1),
                workers_per_query,
            }
        }
    };
    debug_assert!(plan.total_worker_threads() <= threads);
    Ok(plan)
}

/// Recommend independent lanes, packed batching, or block-local reduction as a
/// measured starting point. Optimized dispatch is selected only inside the
/// qualified 100K-plus, 16-thread envelope; smaller cohorts remain independent.
pub fn recommend_search_dispatch(
    bits: u8,
    rows: usize,
    logical_threads: usize,
    mode: SearchThroughputMode,
) -> Result<SearchDispatchPlan> {
    let independent = recommend_search_throughput(bits, rows, logical_threads, mode)?;
    let threads = logical_threads.max(1);
    if rows < 100_000 || threads < 16 {
        return Ok(SearchDispatchPlan::Independent(independent));
    }
    if mode == SearchThroughputMode::LowestLatency {
        return Ok(SearchDispatchPlan::BlockLocalTopK {
            batch_queries: 1,
            workers: threads,
            config: BlockLocalTopKConfig {
                block_rows: if bits == 2 { 1_024 } else { 2_048 },
                local_k: 64,
            },
        });
    }
    let batch_queries = match mode {
        SearchThroughputMode::LowestLatency => 1,
        SearchThroughputMode::Balanced => 4,
        SearchThroughputMode::MaximumThroughput => 8,
    };
    Ok(SearchDispatchPlan::PackedBatch {
        batch_queries,
        workers: threads,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn measured_sixteen_thread_profiles_are_frozen() {
        assert_eq!(
            recommend_search_throughput(2, 16_384, 16, SearchThroughputMode::LowestLatency)
                .unwrap(),
            SearchThroughputPlan {
                concurrent_queries: 1,
                workers_per_query: 4,
            }
        );
        assert_eq!(
            recommend_search_throughput(4, 16_384, 16, SearchThroughputMode::LowestLatency)
                .unwrap(),
            SearchThroughputPlan {
                concurrent_queries: 1,
                workers_per_query: 8,
            }
        );
        for bits in [2, 4] {
            assert_eq!(
                recommend_search_throughput(bits, 100_000, 16, SearchThroughputMode::LowestLatency)
                    .unwrap(),
                SearchThroughputPlan {
                    concurrent_queries: 1,
                    workers_per_query: 16,
                }
            );
            assert_eq!(
                recommend_search_throughput(bits, 100_000, 16, SearchThroughputMode::Balanced)
                    .unwrap(),
                SearchThroughputPlan {
                    concurrent_queries: 4,
                    workers_per_query: 4,
                }
            );
        }
        assert_eq!(
            recommend_search_throughput(2, 100_000, 16, SearchThroughputMode::MaximumThroughput)
                .unwrap(),
            SearchThroughputPlan {
                concurrent_queries: 16,
                workers_per_query: 1,
            }
        );
        assert_eq!(
            recommend_search_throughput(4, 100_000, 16, SearchThroughputMode::MaximumThroughput)
                .unwrap(),
            SearchThroughputPlan {
                concurrent_queries: 8,
                workers_per_query: 2,
            }
        );
    }

    #[test]
    fn plans_never_exceed_the_available_cpu_budget() {
        for threads in 0..=32 {
            for bits in [2, 4] {
                for rows in [1, 16_384, 100_000] {
                    for mode in [
                        SearchThroughputMode::LowestLatency,
                        SearchThroughputMode::Balanced,
                        SearchThroughputMode::MaximumThroughput,
                    ] {
                        let plan = recommend_search_throughput(bits, rows, threads, mode).unwrap();
                        assert!(plan.concurrent_queries >= 1);
                        assert!(plan.workers_per_query >= 1);
                        assert!(plan.total_worker_threads() <= threads.max(1));
                    }
                }
            }
        }
    }

    #[test]
    fn unsupported_bit_width_fails_closed() {
        assert!(matches!(
            recommend_search_throughput(3, 100_000, 16, SearchThroughputMode::Balanced),
            Err(TurboQuantError::UnsupportedBitWidth(3))
        ));
    }

    #[test]
    fn optimized_dispatch_is_selected_only_inside_the_measured_envelope() {
        for bits in [2, 4] {
            assert_eq!(
                recommend_search_dispatch(bits, 100_000, 16, SearchThroughputMode::Balanced)
                    .unwrap(),
                SearchDispatchPlan::PackedBatch {
                    batch_queries: 4,
                    workers: 16,
                }
            );
            assert_eq!(
                recommend_search_dispatch(
                    bits,
                    100_000,
                    16,
                    SearchThroughputMode::MaximumThroughput
                )
                .unwrap(),
                SearchDispatchPlan::PackedBatch {
                    batch_queries: 8,
                    workers: 16,
                }
            );
            assert!(matches!(
                recommend_search_dispatch(
                    bits,
                    16_384,
                    16,
                    SearchThroughputMode::MaximumThroughput
                )
                .unwrap(),
                SearchDispatchPlan::Independent(_)
            ));
            let expected = SearchDispatchPlan::BlockLocalTopK {
                batch_queries: 1,
                workers: 16,
                config: BlockLocalTopKConfig {
                    block_rows: if bits == 2 { 1_024 } else { 2_048 },
                    local_k: 64,
                },
            };
            assert_eq!(
                recommend_search_dispatch(bits, 100_000, 16, SearchThroughputMode::LowestLatency)
                    .unwrap(),
                expected
            );
        }
    }
}
