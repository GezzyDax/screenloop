// Times are read off a wall clock in an operations room, so they are shown the
// European way regardless of what locale the browser happens to be in. Without
// hourCycle the en-US default turns every timestamp into AM/PM.
const DATE_TIME = { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const CLOCK = { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" };

export function formatUnixTime(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "-";
  const milliseconds = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
  return new Intl.DateTimeFormat("ru-RU", { ...DATE_TIME, second: "2-digit" }).format(new Date(milliseconds));
}

export function formatDateTime(value) {
  if (!value) return "-";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ru-RU", DATE_TIME).format(date);
}

export function formatClock(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ru-RU", CLOCK).format(date);
}

// A date without a time, for a column that has to fit two of them side by side.
// The year is left off while it is this one -- an airing window is usually days
// away, and "24 авг" reads faster than "24.08.2026" in a list of twenty rows.
export function formatShortDate(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "";
  const date = new Date(timestamp > 10_000_000_000 ? timestamp : timestamp * 1000);
  if (Number.isNaN(date.getTime())) return "";
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(date);
}

export function formatDuration(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  const padded = (part) => String(part).padStart(2, "0");
  if (hours > 0) return `${hours}:${padded(minutes)}:${padded(rest)}`;
  return `${minutes}:${padded(rest)}`;
}
