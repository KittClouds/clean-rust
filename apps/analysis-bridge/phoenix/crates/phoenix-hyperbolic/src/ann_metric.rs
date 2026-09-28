use crate::sphere::{SphereDistance, SphereMetric};
use crate::{MetricF32, MetricIdentity, MetricKind, PoincareMetric};

const EPS: f32 = 1e-6;

/// Conservative curvature sweep values for benchmarks.
///
/// Use these to test hierarchy quality, boundary saturation, recall,
/// and rerank stability. Do not treat curvature as a magic constant.
/// Let benchmarks decide which geometry earns production work.
pub const DEFAULT_CURVATURE_SWEEP: &[f32] = &[0.1, 0.25, 0.5, 1.0, 2.0, 4.0];

/// High-level role of an ANN metric.
///
/// ANN should stay boring:
/// - generate candidates fast
/// - keep distance monotone and stable
/// - leave mixed/directional/evidence-heavy logic to rerankers
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AnnMetricRole {
    /// Semantic similarity: cosine/angular/chordal neighborhood search.
    Semantic,

    /// Hierarchy/depth search: parent-child, ancestor-descendant,
    /// radial depth, taxonomy, ontology, structural containment.
    Hierarchy,

    /// Hybrid hierarchy interior search.
    ///
    /// This is intentionally still a simple hyperbolic metric, but the label
    /// communicates that the vectors were produced by a hybrid coordinate
    /// compiler: semantic direction + hierarchy radius.
    HybridInterior,
}

/// Geometric family used by a metric.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AnnMetricFamily {
    Sphere,
    Poincare,
    Lorentz,
    Euclidean,
}

/// Lorentz / hyperboloid metric for hyperbolic space.
///
/// Vector layout:
///
/// ```text
/// [time, x_1, x_2, ..., x_n]
/// ```
///
/// The metric assumes points live on the upper sheet of the hyperboloid:
///
/// ```text
/// -t^2 + ||x||^2 = -1 / c
/// t > 0
/// ```
///
/// For curvature parameter `c > 0`, the hyperbolic curvature is `-c`.
///
/// Important:
/// This metric is for vectors already shaped as Lorentz coordinates.
/// If your raw embedding has dimension `d`, your Lorentz vector should usually
/// have dimension `d + 1`, where index 0 is the time coordinate.
///
/// For Phoenix's hybrid space:
/// - use sphere vectors for semantic ANN
/// - use Poincare vectors for pretty interior display/search
/// - use Lorentz vectors when you want hierarchy math in the engine room
#[derive(Clone, Copy, Debug)]
pub struct LorentzMetric {
    pub curvature: f32,
    pub eps: f32,
}

impl Default for LorentzMetric {
    fn default() -> Self {
        Self {
            curvature: 1.0,
            eps: EPS,
        }
    }
}

impl LorentzMetric {
    pub const fn new(curvature: f32) -> Self {
        Self {
            curvature,
            eps: EPS,
        }
    }

    #[inline]
    fn safe_curvature(&self) -> f32 {
        self.curvature.abs().max(EPS)
    }

    #[inline]
    fn spatial_norm_squared(v: &[f32]) -> f32 {
        if v.len() <= 1 {
            return 0.0;
        }

        let mut sum = 0.0f32;
        for &x in &v[1..] {
            if x.is_finite() {
                sum = x.mul_add(x, sum);
            }
        }
        sum
    }

    #[inline]
    fn minkowski_dot(a: &[f32], b: &[f32]) -> f32 {
        let len = a.len().min(b.len());
        if len == 0 {
            return 0.0;
        }

        let mut sum = -a[0] * b[0];

        for i in 1..len {
            sum = a[i].mul_add(b[i], sum);
        }

        sum
    }

    /// Project in-place to the upper hyperboloid sheet by keeping the spatial
    /// coordinates and recomputing the time coordinate.
    ///
    /// Degenerate or invalid vectors become the Lorentz origin:
    ///
    /// ```text
    /// [1 / sqrt(c), 0, 0, ...]
    /// ```
    #[inline]
    fn project_to_hyperboloid(&self, vector: &mut [f32]) {
        if vector.is_empty() {
            return;
        }

        let c = self.safe_curvature();
        let inv_c = 1.0 / c;

        let mut valid = true;
        for x in vector.iter_mut() {
            if !x.is_finite() {
                valid = false;
                *x = 0.0;
            }
        }

        if !valid {
            vector.fill(0.0);
            vector[0] = inv_c.sqrt();
            return;
        }

        let spatial_norm_sq = Self::spatial_norm_squared(vector);
        vector[0] = (inv_c + spatial_norm_sq).sqrt().max(self.eps);
    }
}

impl MetricF32 for LorentzMetric {
    #[inline]
    fn eval(&self, a: &[f32], b: &[f32]) -> f32 {
        if a.is_empty() || b.is_empty() {
            return 0.0;
        }

        let c = self.safe_curvature();
        let sqrt_c = c.sqrt();

        let minkowski = Self::minkowski_dot(a, b);

        // For valid hyperboloid points:
        // distance = acosh(-c * <a,b>_L) / sqrt(c)
        //
        // Numerical noise can push the argument below 1, so clamp.
        let arg = (-c * minkowski).max(1.0);

        if arg <= 1.0 {
            return 0.0;
        }

        fast_acosh(arg) / sqrt_c
    }

    #[inline]
    fn rank_eval(&self, a: &[f32], b: &[f32]) -> f32 {
        self.eval(a, b)
    }

    #[inline]
    fn project_to_ball(&self, vector: &mut [f32]) {
        self.project_to_hyperboloid(vector);
    }

    fn identity(&self) -> MetricIdentity {
        MetricIdentity::known(
            MetricKind::Lorentz,
            [self.curvature.to_bits(), self.eps.to_bits(), 0, 0],
        )
    }
}

/// Small Euclidean metric for tangent/local refinement lanes.
///
/// This is included for convenience but should not become the default global
/// graph metric. Use it for local neighborhoods, tangent-space experiments,
/// and sanity checks.
#[derive(Clone, Copy, Debug, Default)]
pub struct EuclideanMetric;

impl MetricF32 for EuclideanMetric {
    #[inline]
    fn eval(&self, a: &[f32], b: &[f32]) -> f32 {
        let len = a.len().min(b.len());
        let mut sum = 0.0f32;

        for i in 0..len {
            let d = a[i] - b[i];
            sum = d.mul_add(d, sum);
        }

        sum.sqrt()
    }

    #[inline]
    fn rank_eval(&self, a: &[f32], b: &[f32]) -> f32 {
        let len = a.len().min(b.len());
        let mut sum = 0.0f32;

        for i in 0..len {
            let d = a[i] - b[i];
            sum = d.mul_add(d, sum);
        }

        sum
    }

    #[inline]
    fn project_to_ball(&self, _vector: &mut [f32]) {
        // Euclidean tangent/local lanes do not need manifold projection.
    }

    fn identity(&self) -> MetricIdentity {
        MetricIdentity::known(MetricKind::Euclidean, [0; 4])
    }
}

/// Metric selector for ANN candidate generation.
///
/// This intentionally stays boring:
/// - sphere for semantic similarity
/// - Poincare/Lorentz for hierarchy
/// - hybrid interior as a role-explicit Poincare lane
/// - Euclidean only for local/tangent experiments
///
/// Directional hierarchy tests, entailment cones, graph evidence,
/// hubness penalties, recency, and mixed scores belong in rerankers.
#[derive(Clone, Copy, Debug)]
pub enum AnnMetric {
    Poincare(PoincareMetric),
    Lorentz(LorentzMetric),
    Sphere(SphereMetric),

    /// Same math as Poincare, different contract.
    ///
    /// Use this for vectors created by the hybrid coordinate compiler:
    /// semantic direction + hierarchy radius.
    HybridInterior(PoincareMetric),

    /// Local/tangent-space refinement. Avoid using as the global default.
    Euclidean(EuclideanMetric),
}

impl Default for AnnMetric {
    fn default() -> Self {
        Self::sphere_geodesic()
    }
}

impl AnnMetric {
    pub const LABEL_POINCARE: &'static str = "hyperbolic:poincare";
    pub const LABEL_LORENTZ: &'static str = "hyperbolic:lorentz";

    pub const LABEL_SPHERE_COSINE: &'static str = "sphere:cosine";
    pub const LABEL_SPHERE_CHORDAL: &'static str = "sphere:chordal";
    pub const LABEL_SPHERE_CHORDAL_SQUARED: &'static str = "sphere:chordal_squared";
    pub const LABEL_SPHERE_GEODESIC: &'static str = "sphere:geodesic";

    pub const LABEL_HYBRID_INTERIOR: &'static str = "hybrid:interior:poincare";

    pub const LABEL_EUCLIDEAN: &'static str = "euclidean";
    pub const LABEL_TANGENT_EUCLIDEAN: &'static str = "tangent:euclidean";

    pub const fn poincare_default() -> Self {
        Self::Poincare(PoincareMetric { curvature: 1.0 })
    }

    pub const fn poincare(curvature: f32) -> Self {
        Self::Poincare(PoincareMetric { curvature })
    }

    pub const fn lorentz_default() -> Self {
        Self::Lorentz(LorentzMetric {
            curvature: 1.0,
            eps: EPS,
        })
    }

    pub const fn lorentz(curvature: f32) -> Self {
        Self::Lorentz(LorentzMetric {
            curvature,
            eps: EPS,
        })
    }

    pub const fn sphere(distance: SphereDistance) -> Self {
        Self::Sphere(SphereMetric { distance })
    }

    pub const fn sphere_geodesic() -> Self {
        Self::sphere(SphereDistance::Geodesic)
    }

    pub const fn sphere_cosine() -> Self {
        Self::sphere(SphereDistance::Cosine)
    }

    pub const fn sphere_chordal() -> Self {
        Self::sphere(SphereDistance::Chordal)
    }

    pub const fn sphere_chordal_squared() -> Self {
        Self::sphere(SphereDistance::ChordalSquared)
    }

    pub const fn hybrid_interior_default() -> Self {
        Self::HybridInterior(PoincareMetric { curvature: 1.0 })
    }

    pub const fn hybrid_interior(curvature: f32) -> Self {
        Self::HybridInterior(PoincareMetric { curvature })
    }

    pub const fn euclidean() -> Self {
        Self::Euclidean(EuclideanMetric)
    }

    pub const fn label(self) -> &'static str {
        match self {
            Self::Poincare(_) => Self::LABEL_POINCARE,
            Self::Lorentz(_) => Self::LABEL_LORENTZ,
            Self::Sphere(SphereMetric {
                distance: SphereDistance::Cosine,
            }) => Self::LABEL_SPHERE_COSINE,
            Self::Sphere(SphereMetric {
                distance: SphereDistance::Chordal,
            }) => Self::LABEL_SPHERE_CHORDAL,
            Self::Sphere(SphereMetric {
                distance: SphereDistance::ChordalSquared,
            }) => Self::LABEL_SPHERE_CHORDAL_SQUARED,
            Self::Sphere(SphereMetric {
                distance: SphereDistance::Geodesic,
            }) => Self::LABEL_SPHERE_GEODESIC,
            Self::HybridInterior(_) => Self::LABEL_HYBRID_INTERIOR,
            Self::Euclidean(_) => Self::LABEL_EUCLIDEAN,
        }
    }

    pub const fn role(self) -> AnnMetricRole {
        match self {
            Self::Sphere(_) => AnnMetricRole::Semantic,
            Self::Poincare(_) | Self::Lorentz(_) => AnnMetricRole::Hierarchy,
            Self::HybridInterior(_) => AnnMetricRole::HybridInterior,
            Self::Euclidean(_) => AnnMetricRole::Semantic,
        }
    }

    pub const fn family(self) -> AnnMetricFamily {
        match self {
            Self::Sphere(_) => AnnMetricFamily::Sphere,
            Self::Poincare(_) | Self::HybridInterior(_) => AnnMetricFamily::Poincare,
            Self::Lorentz(_) => AnnMetricFamily::Lorentz,
            Self::Euclidean(_) => AnnMetricFamily::Euclidean,
        }
    }

    pub const fn is_semantic(self) -> bool {
        matches!(self.role(), AnnMetricRole::Semantic)
    }

    pub const fn is_hierarchy(self) -> bool {
        matches!(
            self.role(),
            AnnMetricRole::Hierarchy | AnnMetricRole::HybridInterior
        )
    }

    pub const fn is_hyperbolic(self) -> bool {
        matches!(
            self,
            Self::Poincare(_) | Self::Lorentz(_) | Self::HybridInterior(_)
        )
    }

    pub const fn curvature(self) -> Option<f32> {
        match self {
            Self::Poincare(metric) => Some(metric.curvature),
            Self::Lorentz(metric) => Some(metric.curvature),
            Self::HybridInterior(metric) => Some(metric.curvature),
            Self::Sphere(_) | Self::Euclidean(_) => None,
        }
    }

    /// Return the same metric flavor with a different curvature.
    ///
    /// Sphere and Euclidean metrics ignore curvature.
    pub const fn with_curvature(self, curvature: f32) -> Self {
        match self {
            Self::Poincare(_) => Self::poincare(curvature),
            Self::Lorentz(_) => Self::lorentz(curvature),
            Self::HybridInterior(_) => Self::hybrid_interior(curvature),
            Self::Sphere(metric) => Self::Sphere(metric),
            Self::Euclidean(metric) => Self::Euclidean(metric),
        }
    }

    /// Metrics worth benchmarking as ANN candidate generators.
    ///
    /// Keep this small. Rerankers can be exotic; ANN should stay sharp and boring.
    pub fn default_candidate_lanes() -> Vec<Self> {
        vec![
            Self::sphere_cosine(),
            Self::sphere_geodesic(),
            Self::poincare_default(),
            Self::lorentz_default(),
            Self::hybrid_interior_default(),
        ]
    }

    /// Generate hyperbolic sweep lanes for validation.
    pub fn curvature_sweep_for(base: Self) -> Vec<Self> {
        DEFAULT_CURVATURE_SWEEP
            .iter()
            .copied()
            .map(|c| base.with_curvature(c))
            .collect()
    }

    pub fn from_label(label: &str) -> Option<Self> {
        let normalized = label.trim().to_ascii_lowercase();

        match normalized.as_str() {
            Self::LABEL_POINCARE | "poincare" | "poincare:ball" | "hyperbolic" => {
                Some(Self::poincare_default())
            }

            Self::LABEL_LORENTZ | "lorentz" | "hyperboloid" | "hyperbolic:hyperboloid" => {
                Some(Self::lorentz_default())
            }

            Self::LABEL_SPHERE_COSINE | "cosine" | "sphere" | "hypersphere:cosine" => {
                Some(Self::sphere(SphereDistance::Cosine))
            }

            Self::LABEL_SPHERE_CHORDAL | "chordal" | "hypersphere:chordal" => {
                Some(Self::sphere(SphereDistance::Chordal))
            }

            Self::LABEL_SPHERE_CHORDAL_SQUARED
            | "chordal_squared"
            | "chordal-squared"
            | "hypersphere:chordal_squared" => Some(Self::sphere(SphereDistance::ChordalSquared)),

            Self::LABEL_SPHERE_GEODESIC | "geodesic" | "hypersphere" | "hypersphere:geodesic" => {
                Some(Self::sphere_geodesic())
            }

            Self::LABEL_HYBRID_INTERIOR
            | "hybrid"
            | "hybrid:poincare"
            | "hybrid:interior"
            | "semantic_shell:hierarchy_ball" => Some(Self::hybrid_interior_default()),

            Self::LABEL_EUCLIDEAN | Self::LABEL_TANGENT_EUCLIDEAN | "l2" | "tangent" => {
                Some(Self::euclidean())
            }

            _ => None,
        }
    }

    pub fn from_label_or_default(label: &str) -> Self {
        Self::from_label(label).unwrap_or_default()
    }
}

impl MetricF32 for AnnMetric {
    #[inline]
    fn eval(&self, a: &[f32], b: &[f32]) -> f32 {
        match self {
            Self::Poincare(metric) => metric.eval(a, b),
            Self::Lorentz(metric) => metric.eval(a, b),
            Self::Sphere(metric) => metric.eval(a, b),
            Self::HybridInterior(metric) => metric.eval(a, b),
            Self::Euclidean(metric) => metric.eval(a, b),
        }
    }

    #[inline]
    fn rank_eval(&self, a: &[f32], b: &[f32]) -> f32 {
        match self {
            Self::Poincare(metric) => metric.rank_eval(a, b),
            Self::Lorentz(metric) => metric.rank_eval(a, b),
            Self::Sphere(metric) => metric.rank_eval(a, b),
            Self::HybridInterior(metric) => metric.rank_eval(a, b),
            Self::Euclidean(metric) => metric.rank_eval(a, b),
        }
    }

    #[inline]
    fn project_to_ball(&self, vector: &mut [f32]) {
        match self {
            Self::Poincare(metric) => metric.project_to_ball(vector),
            Self::Lorentz(metric) => metric.project_to_ball(vector),
            Self::Sphere(metric) => metric.project_to_ball(vector),
            Self::HybridInterior(metric) => metric.project_to_ball(vector),
            Self::Euclidean(metric) => metric.project_to_ball(vector),
        }
    }

    fn identity(&self) -> MetricIdentity {
        match self {
            Self::Poincare(metric) => metric.identity(),
            Self::Lorentz(metric) => metric.identity(),
            Self::Sphere(metric) => metric.identity(),
            Self::HybridInterior(metric) => MetricIdentity::known(
                MetricKind::HybridInterior,
                [metric.curvature.to_bits(), 0, 0, 0],
            ),
            Self::Euclidean(metric) => metric.identity(),
        }
    }
}

#[inline]
fn fast_acosh(x: f32) -> f32 {
    if x <= 1.0 {
        return 0.0;
    }

    let delta = x - 1.0;
    if delta < 1e-4 {
        (2.0 * delta).sqrt()
    } else if x < 1e6 {
        (x + (x * x - 1.0).sqrt()).ln()
    } else {
        (2.0 * x).ln()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn norm(v: &[f32]) -> f32 {
        v.iter().map(|x| x * x).sum::<f32>().sqrt()
    }

    fn minkowski_self(v: &[f32]) -> f32 {
        if v.is_empty() {
            return 0.0;
        }

        let mut sum = -v[0] * v[0];
        for &x in &v[1..] {
            sum += x * x;
        }
        sum
    }

    #[test]
    fn parses_existing_metric_labels() {
        assert_eq!(
            AnnMetric::from_label_or_default("sphere:geodesic").label(),
            AnnMetric::LABEL_SPHERE_GEODESIC
        );

        assert_eq!(
            AnnMetric::from_label_or_default("hyperbolic:poincare").label(),
            AnnMetric::LABEL_POINCARE
        );

        assert_eq!(
            AnnMetric::from_label_or_default("unknown").label(),
            AnnMetric::LABEL_SPHERE_GEODESIC
        );
    }

    #[test]
    fn parses_new_metric_labels() {
        assert_eq!(
            AnnMetric::from_label_or_default("hyperbolic:lorentz").label(),
            AnnMetric::LABEL_LORENTZ
        );

        assert_eq!(
            AnnMetric::from_label_or_default("hybrid:interior:poincare").label(),
            AnnMetric::LABEL_HYBRID_INTERIOR
        );

        assert_eq!(
            AnnMetric::from_label_or_default("tangent:euclidean").label(),
            AnnMetric::LABEL_EUCLIDEAN
        );
    }

    #[test]
    fn reports_roles() {
        assert!(AnnMetric::sphere_cosine().is_semantic());
        assert!(AnnMetric::poincare_default().is_hierarchy());
        assert!(AnnMetric::lorentz_default().is_hierarchy());
        assert!(AnnMetric::hybrid_interior_default().is_hierarchy());
    }

    #[test]
    fn reports_metric_families() {
        assert_eq!(AnnMetric::sphere_cosine().family(), AnnMetricFamily::Sphere);
        assert_eq!(
            AnnMetric::poincare_default().family(),
            AnnMetricFamily::Poincare
        );
        assert_eq!(
            AnnMetric::hybrid_interior_default().family(),
            AnnMetricFamily::Poincare
        );
        assert_eq!(
            AnnMetric::lorentz_default().family(),
            AnnMetricFamily::Lorentz
        );
        assert_eq!(AnnMetric::euclidean().family(), AnnMetricFamily::Euclidean);
    }

    #[test]
    fn applies_curvature_to_hyperbolic_metrics() {
        assert_eq!(
            AnnMetric::poincare_default()
                .with_curvature(2.0)
                .curvature(),
            Some(2.0)
        );
        assert_eq!(
            AnnMetric::lorentz_default().with_curvature(0.5).curvature(),
            Some(0.5)
        );
        assert_eq!(
            AnnMetric::hybrid_interior_default()
                .with_curvature(4.0)
                .curvature(),
            Some(4.0)
        );

        assert_eq!(
            AnnMetric::sphere_cosine().with_curvature(4.0).curvature(),
            None
        );
    }

    #[test]
    fn candidate_lanes_stay_small() {
        let lanes = AnnMetric::default_candidate_lanes();

        assert!(lanes.iter().any(|m| matches!(m, AnnMetric::Sphere(_))));
        assert!(lanes.iter().any(|m| matches!(m, AnnMetric::Poincare(_))));
        assert!(lanes.iter().any(|m| matches!(m, AnnMetric::Lorentz(_))));
        assert!(lanes
            .iter()
            .any(|m| matches!(m, AnnMetric::HybridInterior(_))));
        assert!(lanes.len() <= 6);
    }

    #[test]
    fn curvature_sweep_keeps_metric_flavor() {
        let sweep = AnnMetric::curvature_sweep_for(AnnMetric::lorentz_default());

        assert_eq!(sweep.len(), DEFAULT_CURVATURE_SWEEP.len());

        for metric in sweep {
            assert!(matches!(metric, AnnMetric::Lorentz(_)));
            assert!(metric.curvature().is_some());
        }
    }

    #[test]
    fn lorentz_projection_places_vector_on_hyperboloid() {
        let metric = LorentzMetric::default();
        let mut v = vec![0.0, 3.0, 4.0];

        metric.project_to_ball(&mut v);

        let expected = -1.0 / metric.curvature;
        let actual = minkowski_self(&v);

        assert!((actual - expected).abs() < 1e-4);
        assert!(v[0] > 0.0);
    }

    #[test]
    fn lorentz_origin_distance_is_zero() {
        let metric = LorentzMetric::default();
        let mut a = vec![0.0, 0.0, 0.0];
        let mut b = vec![0.0, 0.0, 0.0];

        metric.project_to_ball(&mut a);
        metric.project_to_ball(&mut b);

        let d = metric.eval(&a, &b);
        assert!(d.abs() < 1e-6);
    }

    #[test]
    fn lorentz_distance_increases_with_spatial_separation() {
        let metric = LorentzMetric::default();

        let mut origin = vec![0.0, 0.0, 0.0];
        let mut near = vec![0.0, 0.25, 0.0];
        let mut far = vec![0.0, 2.0, 0.0];

        metric.project_to_ball(&mut origin);
        metric.project_to_ball(&mut near);
        metric.project_to_ball(&mut far);

        let d_near = metric.eval(&origin, &near);
        let d_far = metric.eval(&origin, &far);

        assert!(d_near < d_far);
    }

    #[test]
    fn euclidean_rank_uses_squared_distance() {
        let metric = EuclideanMetric;
        let a = vec![0.0, 0.0];
        let b = vec![3.0, 4.0];

        assert_eq!(metric.rank_eval(&a, &b), 25.0);
        assert_eq!(metric.eval(&a, &b), 5.0);
    }

    #[test]
    fn sphere_projection_still_normalizes() {
        let metric = AnnMetric::sphere_cosine();
        let mut v = vec![3.0, 4.0];

        metric.project_to_ball(&mut v);

        assert!((norm(&v) - 1.0).abs() < 1e-5);
    }

    #[test]
    fn hybrid_interior_behaves_like_poincare_lane() {
        let metric = AnnMetric::hybrid_interior_default();
        let mut v = vec![10.0, 0.0];

        metric.project_to_ball(&mut v);

        assert!(norm(&v) < 1.0);
        assert_eq!(metric.role(), AnnMetricRole::HybridInterior);
        assert_eq!(metric.family(), AnnMetricFamily::Poincare);
    }
}
