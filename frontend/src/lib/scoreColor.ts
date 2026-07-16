/** Continuous green-to-red color grade for a 0-100 lead score -- replaces
 * the old discrete high/medium/low tier labels. Returns an HSL hue only;
 * saturation/lightness are applied in CSS so light/dark themes stay
 * readable without recomputing color here. */
export function scoreHue(score: number): number {
  const clamped = Math.max(0, Math.min(100, score))
  // 100 -> 145deg (green), 50 -> ~72deg (amber), 0 -> 0deg (red).
  return Math.round((clamped / 100) * 145)
}
