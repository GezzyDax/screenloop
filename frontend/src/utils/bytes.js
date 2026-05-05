export function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const precision = index === 0 ? 0 : value / 1024 ** index >= 10 ? 1 : 2;
  return `${(value / 1024 ** index).toFixed(precision)} ${units[index]}`;
}
