//! 低模质量检查插件的 Rust 内核。
//!
//! 本 crate 只承载**几何计算**部分：Blender 侧的注册、面板与操作符仍由
//! Python 负责。把计算抽出来的直接好处是它可以脱离 Blender 独立测试
//! （`cargo test`），而 Python 侧只需通过一层薄绑定调用。
//!
//! 约定：
//!
//! * 所有长度单位与 Blender 场景一致（无量纲的模型单位）。
//! * 任何可能 panic 的路径都由调用方用 `catch_unwind` 兜住，
//!   绝不把 panic 抛进 Python 解释器。

use std::collections::HashMap;

/// 内核版本号（取自 `Cargo.toml`）。
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// 由「允许偏离的最大角度（弧度）」换算余弦阈值。
///
/// Python 侧的共线顶点检测使用同一判据：两条**单位**边向量的点积绝对值
/// `|cos θ| >= cos(threshold)` 即视为共线。这里把换算收敛到内核，
/// 避免两侧各写一份而漂移。
pub fn cos_threshold(threshold: f64) -> f64 {
    threshold.max(0.0).cos()
}

/// 三维点。
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    /// X 分量。
    pub x: f64,
    /// Y 分量。
    pub y: f64,
    /// Z 分量。
    pub z: f64,
}

impl Point {
    /// 构造一个点。
    pub fn new(x: f64, y: f64, z: f64) -> Self {
        Self { x, y, z }
    }

    /// 逐分量相减。
    pub fn sub(&self, other: &Point) -> Point {
        Point::new(self.x - other.x, self.y - other.y, self.z - other.z)
    }

    /// 点积。
    pub fn dot(&self, other: &Point) -> f64 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }

    /// 模长。
    pub fn length(&self) -> f64 {
        self.dot(self).sqrt()
    }

    /// 到另一点的**距离平方**（省去开方，仅用于比较）。
    pub fn distance_squared(&self, other: &Point) -> f64 {
        let d = self.sub(other);
        d.dot(&d)
    }

    /// 单位化；零向量返回 `None`。
    pub fn normalized(&self) -> Option<Point> {
        let len = self.length();
        if len > 0.0 {
            Some(Point::new(self.x / len, self.y / len, self.z / len))
        } else {
            None
        }
    }
}

/// 空间网格的单元键。
type Cell = (i64, i64, i64);

/// 计算点所在的网格单元。
fn cell_of(p: &Point, size: f64) -> Cell {
    (
        (p.x / size).floor() as i64,
        (p.y / size).floor() as i64,
        (p.z / size).floor() as i64,
    )
}

/// 把点按 `size` 为边长装进空间网格。
fn build_grid(points: &[Point], size: f64) -> HashMap<Cell, Vec<usize>> {
    let mut grid: HashMap<Cell, Vec<usize>> = HashMap::new();
    for (i, p) in points.iter().enumerate() {
        grid.entry(cell_of(p, size)).or_default().push(i);
    }
    grid
}

/// 顶点质量检测算法组（与 Python 侧语义一致）。
pub mod vertex {
    use super::{build_grid, cell_of, cos_threshold, Point};
    use std::collections::{BTreeSet, HashSet};

    /// 邻接表：顶点 → 与它通过边直接相连的顶点集合。
    pub fn adjacency(points_len: usize, edges: &[(usize, usize)]) -> Vec<HashSet<usize>> {
        let mut adj: Vec<HashSet<usize>> = vec![HashSet::new(); points_len];
        for &(a, b) in edges {
            if a < points_len && b < points_len {
                adj[a].insert(b);
                adj[b].insert(a);
            }
        }
        adj
    }

    /// 共线顶点：度数恰为 2、非边界，且两条相邻边方向几乎相反的顶点。
    ///
    /// 判据与 Python 侧一致：单位边向量的点积绝对值 `|cos θ| >= cos(threshold)`。
    pub fn collinear_vertices(
        points: &[Point],
        edges: &[(usize, usize)],
        boundary: &[bool],
        threshold: f64,
    ) -> Vec<usize> {
        let cos_t = cos_threshold(threshold);
        let adj = adjacency(points.len(), edges);
        let mut out = Vec::new();
        for (v, links) in adj.iter().enumerate() {
            if boundary.get(v).copied().unwrap_or(false) || links.len() != 2 {
                continue;
            }
            let mut it = links.iter();
            let n0 = *it.next().expect("度数已确认为 2");
            let n1 = *it.next().expect("度数已确认为 2");
            let d0 = points[n0].sub(&points[v]);
            let d1 = points[n1].sub(&points[v]);
            if let (Some(u0), Some(u1)) = (d0.normalized(), d1.normalized()) {
                if u0.dot(&u1).abs() >= cos_t {
                    out.push(v);
                }
            }
        }
        out
    }

    /// 未焊接点：空间距离不超过阈值、但两者之间不存在边的顶点。
    ///
    /// 使用**邻域网格**（查询时检查相邻 27 个格子）而非单格量化，
    /// 因此不存在「两点恰好落在格子边界两侧而漏检」的问题。
    pub fn unwelded_vertices(
        points: &[Point],
        edges: &[(usize, usize)],
        threshold: f64,
    ) -> Vec<usize> {
        if points.is_empty() || threshold <= 0.0 {
            return Vec::new();
        }
        let grid = build_grid(points, threshold);
        let adj = adjacency(points.len(), edges);
        let t2 = threshold * threshold;
        let mut out = BTreeSet::new();
        for (i, p) in points.iter().enumerate() {
            let (cx, cy, cz) = cell_of(p, threshold);
            for dx in -1..=1 {
                for dy in -1..=1 {
                    for dz in -1..=1 {
                        let Some(bucket) = grid.get(&(cx + dx, cy + dy, cz + dz)) else {
                            continue;
                        };
                        for &j in bucket {
                            if j == i || p.distance_squared(&points[j]) > t2 {
                                continue;
                            }
                            if adj[i].contains(&j) {
                                continue;
                            }
                            out.insert(i);
                            out.insert(j);
                        }
                    }
                }
            }
        }
        out.into_iter().collect()
    }

    /// 密集顶点：以 `distance_threshold` 为半径（含自身）的球内顶点数
    /// 达到 `count_threshold + 1` 的顶点。
    pub fn dense_vertices(
        points: &[Point],
        distance_threshold: f64,
        count_threshold: usize,
    ) -> Vec<usize> {
        if points.is_empty() || distance_threshold <= 0.0 {
            return Vec::new();
        }
        let grid = build_grid(points, distance_threshold);
        let t2 = distance_threshold * distance_threshold;
        let mut out = Vec::new();
        for (i, p) in points.iter().enumerate() {
            let (cx, cy, cz) = cell_of(p, distance_threshold);
            let mut count = 0usize;
            for dx in -1..=1 {
                for dy in -1..=1 {
                    for dz in -1..=1 {
                        let Some(bucket) = grid.get(&(cx + dx, cy + dy, cz + dz)) else {
                            continue;
                        };
                        for &j in bucket {
                            if p.distance_squared(&points[j]) <= t2 {
                                count += 1;
                            }
                        }
                    }
                }
            }
            if count > count_threshold {
                out.push(i);
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_is_not_empty() {
        assert!(!version().is_empty());
    }
    #[test]
    fn cos_threshold_at_zero_is_one() {
        assert!((cos_threshold(0.0) - 1.0).abs() < 1e-12);
    }

    #[test]
    fn cos_threshold_matches_standard_library() {
        assert!((cos_threshold(0.01) - 0.01_f64.cos()).abs() < 1e-15);
    }

    #[test]
    fn cos_threshold_clamps_negative_input() {
        // 负阈值没有物理意义，一律按 0 处理（等价于「只要方向完全一致」）
        assert!((cos_threshold(-1.0) - 1.0).abs() < 1e-12);
    }
}

#[cfg(test)]
mod vertex_tests {
    use super::vertex::{collinear_vertices, dense_vertices, unwelded_vertices};
    use super::Point;

    fn p(x: f64, y: f64, z: f64) -> Point {
        Point::new(x, y, z)
    }

    #[test]
    fn collinear_ignores_high_degree_vertex() {
        // 顶点 1 同时连到 0 / 2 / 3，度数为 3，不属于「直线上的多余点」
        let points = vec![
            p(0.0, 0.0, 0.0),
            p(1.0, 0.0, 0.0),
            p(2.0, 0.0, 0.0),
            p(1.0, 1.0, 0.0),
        ];
        let edges = vec![(0, 1), (1, 2), (1, 3)];
        let boundary = vec![true, false, true, true];
        assert!(collinear_vertices(&points, &edges, &boundary, 0.01).is_empty());
    }

    #[test]
    fn collinear_detects_degree_two_straight() {
        let points = vec![p(0.0, 0.0, 0.0), p(1.0, 0.0, 0.0), p(2.0, 0.0, 0.0)];
        let edges = vec![(0, 1), (1, 2)];
        let boundary = vec![true, false, true];
        assert_eq!(
            collinear_vertices(&points, &edges, &boundary, 0.01),
            vec![1]
        );
    }

    #[test]
    fn collinear_respects_threshold() {
        // 在顶点 1 处转弯 90°：threshold = 1.5 rad 时不该判为共线
        let points = vec![p(0.0, 0.0, 0.0), p(1.0, 0.0, 0.0), p(1.0, 1.0, 0.0)];
        let edges = vec![(0, 1), (1, 2)];
        let boundary = vec![true, false, true];
        assert!(collinear_vertices(&points, &edges, &boundary, 1.5).is_empty());
    }

    #[test]
    fn unwelded_detects_coincident_unlinked() {
        let points = vec![p(0.0, 0.0, 0.0), p(0.0, 0.0, 0.0), p(1.0, 0.0, 0.0)];
        let edges = vec![(0, 2), (1, 2)];
        assert_eq!(unwelded_vertices(&points, &edges, 0.001), vec![0, 1]);
    }

    #[test]
    fn unwelded_ignores_linked_neighbours() {
        let points = vec![p(0.0, 0.0, 0.0), p(0.0005, 0.0, 0.0)];
        let edges = vec![(0, 1)];
        assert!(unwelded_vertices(&points, &edges, 0.001).is_empty());
    }

    #[test]
    fn unwelded_across_grid_boundary() {
        // 两点相距 0.0002（< 0.001），但落在相邻网格单元——邻域查询不会漏
        let points = vec![p(0.0004, 0.0, 0.0), p(0.0006, 0.0, 0.0), p(1.0, 0.0, 0.0)];
        let edges = vec![(0, 2), (1, 2)];
        assert_eq!(unwelded_vertices(&points, &edges, 0.001), vec![0, 1]);
    }

    #[test]
    fn dense_detects_cluster() {
        let points: Vec<Point> = (0..6).map(|i| p(f64::from(i) * 0.01, 0.0, 0.0)).collect();
        assert_eq!(dense_vertices(&points, 0.1, 5).len(), 6);
    }

    #[test]
    fn dense_ignores_sparse_points() {
        let points: Vec<Point> = (0..6).map(|i| p(f64::from(i) * 10.0, 0.0, 0.0)).collect();
        assert!(dense_vertices(&points, 0.1, 5).is_empty());
    }
}

/// Python 绑定层（PyO3 / abi3-py38）。
///
/// 约定：
///
/// * 入参一律用**扁平数组**（点用 `x, y, z` 依次排列），避免把 Rust 结构体
///   暴露给 Python，边界只有一层。
/// * 所有可能 panic 的路径都由 [`pybind::guard`] 兜住并映射为
///   `PyRuntimeError`——**绝不让 panic 逃逸到 Python 解释器**。
#[cfg(feature = "python")]
mod pybind {
    use crate::{vertex, Point};
    use pyo3::exceptions::PyRuntimeError;
    use pyo3::prelude::*;
    use std::panic::{catch_unwind, AssertUnwindSafe};

    /// 把扁平数组还原为点列表。
    fn points_from_flat(flat: &[f64]) -> PyResult<Vec<Point>> {
        if flat.len() % 3 != 0 {
            return Err(PyRuntimeError::new_err(
                "points 长度必须是 3 的倍数（x, y, z 依次排列）",
            ));
        }
        Ok(flat
            .chunks_exact(3)
            .map(|c| Point::new(c[0], c[1], c[2]))
            .collect())
    }

    /// 把扁平数组还原为边列表。
    fn edges_from_flat(flat: &[usize]) -> PyResult<Vec<(usize, usize)>> {
        if flat.len() % 2 != 0 {
            return Err(PyRuntimeError::new_err(
                "edges 长度必须是 2 的倍数（起点, 终点 依次排列）",
            ));
        }
        Ok(flat.chunks_exact(2).map(|c| (c[0], c[1])).collect())
    }

    /// 捕获 panic 并映射为 Python 异常。
    fn guard<F, T>(f: F) -> PyResult<T>
    where
        F: FnOnce() -> PyResult<T>,
    {
        match catch_unwind(AssertUnwindSafe(f)) {
            Ok(value) => value,
            Err(_) => Err(PyRuntimeError::new_err(
                "lowcheck_core 内部错误（panic 已被捕获，未逃逸到 Python）",
            )),
        }
    }

    /// 内核版本号。
    #[pyfunction]
    fn kernel_version() -> &'static str {
        crate::version()
    }

    /// 共线顶点检测。
    #[pyfunction]
    fn collinear_vertices(
        points: Vec<f64>,
        edges: Vec<usize>,
        boundary: Vec<bool>,
        threshold: f64,
    ) -> PyResult<Vec<usize>> {
        guard(|| {
            let pts = points_from_flat(&points)?;
            let eds = edges_from_flat(&edges)?;
            Ok(vertex::collinear_vertices(&pts, &eds, &boundary, threshold))
        })
    }

    /// 未焊接点检测。
    #[pyfunction]
    fn unwelded_vertices(
        points: Vec<f64>,
        edges: Vec<usize>,
        threshold: f64,
    ) -> PyResult<Vec<usize>> {
        guard(|| {
            let pts = points_from_flat(&points)?;
            let eds = edges_from_flat(&edges)?;
            Ok(vertex::unwelded_vertices(&pts, &eds, threshold))
        })
    }

    /// 密集顶点检测。
    #[pyfunction]
    fn dense_vertices(
        points: Vec<f64>,
        distance_threshold: f64,
        count_threshold: usize,
    ) -> PyResult<Vec<usize>> {
        guard(|| {
            let pts = points_from_flat(&points)?;
            Ok(vertex::dense_vertices(
                &pts,
                distance_threshold,
                count_threshold,
            ))
        })
    }

    /// 扩展模块入口。
    #[pymodule]
    fn lowcheck_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add("__version__", crate::version())?;
        m.add_function(wrap_pyfunction!(kernel_version, m)?)?;
        m.add_function(wrap_pyfunction!(collinear_vertices, m)?)?;
        m.add_function(wrap_pyfunction!(unwelded_vertices, m)?)?;
        m.add_function(wrap_pyfunction!(dense_vertices, m)?)?;
        Ok(())
    }
}
