# DH-01: anatomical routing and delayed local reinforcement

Status: execution protocol. The launcher seals this document, code, executable,
configuration and extracted inputs BEFORE any biological-slice task execution.

## Question and scope

Does a coarse, anatomy-constrained DAN-to-MBON modulation map improve delayed
reinforcement of cue-action associations compared with degree-matched shuffled
routing, using the same fixed local covariance learning rule?

This is a synthetic algorithm experiment on selected MaleCNS v1.0 wiring. It is
not a reconstruction of a behaving fly, a test of sentience, or biological
validation of dopamine routing. No learning-rule search is included in DH-01.

The first deliverable includes the anatomy census, extraction boundary, null
integrity checks, engineering qualification, a frozen execution manifest, raw
paired outcomes, and an analysis that can report a negative result.

## Source and selection

Official source: https://male-cns.janelia.org/download/ (CC-BY; FlyEM/Janelia,
Cambridge, MRC LMB, Google Research and collaborators).

Download annotations, neurotransmitter predictions, and connection weights with
SHA-256 and HTTP source metadata. Curated annotations are not a complete neuron
universe. Full connection weights include non-neuronal/unannotated segments.
Retain only status=Traced, somaSide in L/R, classes ALPN, Kenyon_Cell, MBON, DAN,
and type APL. All admission/exclusion counts must be reported. Left and right
are two related anatomical slices of ONE specimen, not independent animals.
Each selected hemisphere is analysed separately; crossing/outside edges are
counted rather than silently interpreted as absent anatomy.

Record neurotransmitter predictions/confidence and ground truth separately.
No inferred transmitter label is treated as a measured functional sign.
Geometry, receptor expression, and synapse-specific modulation remain unavailable.

## Model assumptions

ALPNs receive synthetic sparse binary cues. Weighted ALPN-to-KC projections
produce a top-5-percent KC code (at least one active KC); this hard sparsification
is an invented global inhibitory abstraction, not inferred APL dynamics.
KC-to-MBON weights are the only plastic weights. MBONs are stochastic binary
units. A fixed balanced random partition of MBONs defines two actions; it is
not an anatomical valence assignment and never changes using reward or targets.
KC-to-DAN and signed MBON-to-DAN connections produce contextual DAN activity.
DAN-to-MBON connections define a BINARY candidate routing map. Each incoming
map row is averaged and gains are normalized to equal total delivered
modulation across conditions. Applying an MBON's modulation to all its incoming
KC synapses is explicitly an assumed cell-level broadcast.

Unmodelled selected edges and outside inputs are recorded. The runtime uses the
specified feedforward processing and MBON-to-DAN feedback within a stimulus
event; it does not claim to reproduce the extracted circuit's full recurrence.

## Factorial controls

| Arm | Signal topology | DAN-to-MBON routing |
| --- | --- | --- |
| A | Anatomical | Anatomical |
| B | Same as A | Degree-preserving double-edge swaps |
| C | Degree-preserving rewired signal layers | Anatomical |
| D | Same as C | Same shuffled routing as B |
| E | Same as A | Uniform global modulation |
| Z | Same as A | Plasticity disabled |

Signal layers are ALPN-to-KC, KC-to-MBON, KC-to-DAN, MBON-to-DAN. Swaps preserve
the exact source and destination binary degrees in each layer and disallow
duplicate edges. Synapse-count weights travel with the source edge, preserving
outgoing strength and the layer weight multiset, not incoming strength or
cell-type-pair counts. C/D are secondary coarse nulls, not fully anatomy-matched
nulls. Routing ignores multiplicity in both A and B. Report swap acceptance and
edge retention; failed/degenerate randomizations cannot support a routing claim.

## Local rule and information boundary

At each stimulus event, e_ij <- exp(-1/tau)*e_ij + x_i*(y_j-b_j).
b_j <- 0.99*b_j + 0.01*y_j is a local postsynaptic running baseline.
At delayed reward, w_ij <- clip(w_ij + eta*m_j*e_ij, 0, 2).
Eligibility is cleared between trials, not between the cue and distractors.
No eligibility normalization by reward delay, hidden target, correct action,
task phase, or circuit identity is allowed. The environment delivers only scalar
reward (+1/-1) after the sampled action and distractors. Modulation is reward
times the current contextual gain. No autodiff, activation tape, transpose
weights, backward traversal, or gradient-based fitting is used.

The environment owns targets and cue-action mappings. Encoders receive input
only; the fixed readout receives current MBON activity only; the plasticity
kernel receives weights, eligibility, and local modulation only.

Trial termination is an externally supplied reset boundary. Clearing eligibility
and resetting DAN activity at that boundary are declared model assumptions.
The local baseline is a postsynaptic state, not an environment label. Eligibility
decay uses an algebraically equivalent lazy scale; synthetic tests compare it
against explicit per-event decay.

## Frozen numerical implementation

24 independent computational seed bundles (1000 through 1023). Four settings:
eligibility tau in {4,16} stimulus events crossed with assumed glutamatergic
MBON feedback sign in {-1,+1}. All use eta=0.05. GABA feedback is negative,
acetylcholine positive, and unresolved MBON transmitters use positive feedback
with their count disclosed. This is a limited sensitivity analysis, not a full
uncertainty distribution over receptors or membrane dynamics.

Each cue or distractor activates floor(0.2*n_ALPN) distinct ALPNs. Fixed weighted
projection is normalized by incoming synapse counts. The top floor(n_KC/20)
KCs are activated, with deterministic index tie-breaking. There are 32 distinct
generated distractor patterns per task; cue-code uniqueness is checked. The
task-transfer suite uses a different input seed salt and 32 fresh cue patterns.
Input-derived fixed features are cached before online learning.

For a KC-to-MBON edge of multiplicity c, initial weight is
min(2, 0.15*c*fanin/sum_incoming_counts). MBON input is the sum of active weights
divided by max(1,sqrt(0.05*fanin)), minus a fixed initial-activity bias of
0.05*sum(initial_weights)/that denominator. Spike probability is sigmoid(2*input).
The action is the sign of the fixed random +/- readout applied to (spikes-0.5),
with an independent random tie-break. Readout signs are unrelated to transmitter.

DAN contextual input is normalized KC input k and signed normalized MBON input b.
The per-event DAN target is 0.25+0.75*sigmoid(20*(k-0.05)+2*b), low-pass filtered
with old/new coefficients 0.5/0.5 and initialized to 0.5 each trial. An MBON's
candidate gain is the unweighted mean of its connected DAN activities; no route
means zero. A global scalar normalization makes sum(gain_j*plastic_fanin_j)
equal the plastic-edge count. This normalization is additional nonlocal model
machinery, used identically across routed arms, and never consults task targets.
Uniform modulation uses gain=1; disabled plasticity never updates a weight.

Acquisition and reversal each contain 256 online trials. The primary and left
suites have four distractors; task transfer has twelve. Before reversal and
after the final trial, 16 repetitions per cue measure a frozen-weight probe.
Probes update neither baseline, DAN state nor eligibility; their RNG is separate
from the saved/restored online stream. Probe work is included in online edge
visit counters, while initial feature construction is included only in wall time.

Twenty proposal attempts per edge are used for null swaps. Routing must accept
at least one swap and retain less than 95% of original pairs. These are finite
swap-chain nulls: exact uniform sampling or Markov-chain mixing is not claimed.
Secondary anatomy diagnostics count reciprocal MBON-DAN pairs and triangles
KC->MBON, KC->DAN, DAN->MBON against routing nulls; no candidate is selected using
those counts. Exact cell-type-pair counts and geometry are not preserved by
these coarse nulls, including the B routing control.

Bootstrap: 20,000 resamples of the 24 complete seed bundles, fixed analysis seed
20260911. No biological-task discovery outcomes are used for model selection;
synthetic engineering qualification precedes this first frozen run. All three
suites and every dynamics setting are fixed in advance and fully reported.

## Tasks, splits, and analysis

Synthetic implementation tests and benchmarks are excluded from scientific
outcomes. Execution details and seeds are written to machine-readable config
before the first biological-slice task run. Seal source, lockfile, executable,
input digests, config, and analysis code. Preserve every attempted run.

Primary task: 16 balanced randomly labelled cues, 256 acquisition trials and
256 reversal trials; the cue triggers an immediate action, followed by randomly
generated distractors and a delayed reward for that action. This tests delayed
reinforcement, not delayed response. Secondary transfer: 32 fresh cues, a new
cue mapping and more distractors. No architecture-family transfer is claimed.

Primary endpoint: paired A-B difference in overall online accuracy (acquisition
and reversal equally weighted), averaged over prespecified dynamics settings.
Independent computational seed bundles include task/readout/randomization seeds;
configurations and hemispheres are not independent replicates. Right hemisphere
is primary; left is related structural transfer. Bootstrap whole seed bundles
for the primary 95% interval; one primary test. Other comparisons are descriptive.

Support requires a positive lower primary confidence bound, positive point
effect in every prespecified dynamics setting, and positive held-out task and
left-slice point effects. Otherwise report no support or mixed evidence.
This gate supports only the specified synthetic model family. Report learning
curves, late acquisition and reversal accuracy, retention before reversal,
work counts, simulator-state bytes, hot-loop allocations, and wall time.

The analysis never chooses a favourable task, seed, hemisphere, or dynamics
setting after outcomes. Resource costs include all arms and failed runs. No
evolutionary search or asynchronous runtime will be added to rescue DH-01.
