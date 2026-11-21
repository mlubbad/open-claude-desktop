// Fuzzy (subsequence) filtering for the command palette. Pure + testable.

export function subsequence(text: string, query: string): boolean {
  let i = 0;
  for (let k = 0; k < text.length && i < query.length; k++) {
    if (text[k] === query[i]) i++;
  }
  return i === query.length;
}

export function filterByLabel<T extends { label: string }>(items: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((it) => subsequence(it.label.toLowerCase(), q));
}
