// Short tooltips for filters, columns and histograms. docs/METRICS.md has the full text.

export const METRIC_HELP: Record<string, string> = {
  metric_version: 'Metric formula version to filter/sort by — see docs/METRICS.md.',
  engine_id: 'Restrict to one engine row (identity = binary + options, not just name).',
  min_sign_flips: 'Minimum count of sign changes across the clamped score ladder.',
  min_cp_range: 'Minimum spread (max - min) of clamped cp across the ladder.',
  max_settle_dev: 'Maximum deviation of early rungs from the settled top-rung score.',
  min_top_rung: 'Minimum anchor rung: v1 is a fixed run cap, v2 the deepest complete prefix.',
  has_mate: 'Whether any anchored rung found a forced mate (raw score_kind = mate).',
  min_mate_found_rung: 'Minimum node count of the shallowest rung that found a mate.',
  position_id: 'Internal position row id.',
  epd: 'Normalized 4-field EPD identifying the position.',
  top_rung: 'Anchor rung the row is computed through.',
  sign_flips: 'Sign changes across the clamped score ladder, shallow to top_rung.',
  cp_range: 'Spread (max - min) of clamped cp across the ladder.',
  settle_dev: 'Max deviation of early rungs from the top-rung score.',
  version_disagreement: 'Cross-engine spread at the shared/common-anchor rung; null with no other engine.',
  mate_found_rung: 'Shallowest rung that found a forced mate (raw score_kind), null if none.',
}
