export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  const units: [number, string][] = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [86400 * 30, "day"],
  ];
  if (abs < 5) return "just now";
  let divisor = 1;
  let unit = "second";
  for (const [limit, name] of units) {
    unit = name;
    if (abs < limit) break;
    divisor = limit;
  }
  if (abs >= 86400 * 30) return formatDateTime(iso);
  const count = Math.max(1, Math.floor(abs / divisor));
  const text = `${count} ${unit}${count === 1 ? "" : "s"}`;
  return seconds < 0 ? `${text} ago` : `in ${text}`;
}

export function formatDuration(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (Number.isNaN(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} s`;
}
