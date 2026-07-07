// The personalized, context-aware empty-state greeting (contract §0.3 / §8.1).
// Time-of-day + optional first name, with a few variants so it doesn't read the same
// every launch. Pure + deterministic given (hour, name, variantSeed) for testability.

export function timeBucket(hour: number): "morning" | "afternoon" | "evening" | "late" {
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 17) return "afternoon";
  if (hour >= 17 && hour < 22) return "evening";
  return "late";
}

const TEMPLATES: Record<ReturnType<typeof timeBucket>, string[]> = {
  morning: ["Good morning, {name}", "Morning, {name}", "Ready when you are, {name}"],
  afternoon: ["Good afternoon, {name}", "Afternoon, {name}", "What's next, {name}?"],
  evening: ["Good evening, {name}", "Evening, {name}", "Winding down, {name}?"],
  late: ["Up late, {name}?", "Burning the midnight oil, {name}?", "Still going, {name}?"],
};

// Build the greeting. `name` optional (omitted → no trailing name); `variantSeed`
// picks among the bucket's templates; `hour` defaults to now (24h).
export function greeting(name?: string, hour?: number, variantSeed = 0): string {
  const h = hour ?? new Date().getHours();
  const bucket = timeBucket(h);
  const variants = TEMPLATES[bucket];
  const tpl = variants[Math.abs(variantSeed) % variants.length];
  const first = (name ?? "").trim().split(/\s+/)[0] ?? "";
  if (!first) {
    // Nameless fallbacks read naturally without the trailing ", {name}".
    return tpl.replace(/,?\s*\{name\}\??/, (m) => (m.includes("?") ? "?" : "")).trim() || "Where should we start?";
  }
  return tpl.replace("{name}", first);
}
