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
