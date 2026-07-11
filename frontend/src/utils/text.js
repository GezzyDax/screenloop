export function redactTokens(value) {
  if (!value) return "";
  return String(value).replace(/token=[^&\s]+/g, "token=...");
}
