import { Network, Radar, Server, Wifi } from "@lucide/vue";
import { useI18n } from "../i18n";

const { t } = useI18n();

export const healthChecks = [
  { key: "ping_reachable", labelKey: "healthPing", icon: Wifi },
  { key: "dlna_reachable", labelKey: "healthDlna", icon: Network },
  { key: "soap_ready", labelKey: "healthSoap", icon: Server },
  { key: "streaming", labelKey: "healthStream", icon: Radar },
];

export function healthReason(tv) {
  if (tv.last_error) return tv.last_error;
  if (!tv.ping_reachable) return t("reasonPingUnavailable");
  if (!tv.dlna_reachable) return t("reasonDlnaUnavailable");
  if (!tv.soap_ready) return t("reasonSoapUnavailable");
  if (tv.streaming) return t("reasonStreaming");
  if (tv.online) return t("reasonReady");
  return t("reasonWaitingDiscovery");
}

export function playbackDuration(tv) {
  return Number(tv.current_media_duration_seconds || 0);
}

export function playbackElapsed(tv) {
  const startedAt = Number(tv.playback_started_at || 0);
  if (!startedAt || !tv.current_media_id) return 0;
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  const duration = playbackDuration(tv);
  return duration ? Math.min(elapsed, duration) : elapsed;
}

export function playbackProgress(tv) {
  const duration = playbackDuration(tv);
  if (!duration) return 0;
  return Math.min(100, Math.round((playbackElapsed(tv) / duration) * 100));
}

export function tvStateClass(tv) {
  if (tv.last_error) return "bad";
  if (tv.streaming || tv.online) return "ok";
  return "bad";
}

export function stateLabel(state) {
  const value = state || "UNKNOWN";
  const key = `state_${value}`;
  const text = t(key);
  return text === key ? value : text;
}

export function onlineLabel(tv) {
  return tv.online ? t("statusOnline") : t("statusOffline");
}

export function shortUrl(value) {
  if (!value) return "-";
  try {
    const url = new URL(value);
    const leaf = url.pathname.split("/").filter(Boolean).pop();
    return `${url.host}${leaf ? `/${leaf}` : ""}`;
  } catch (_) {
    return String(value).replace(/^https?:\/\//, "").slice(0, 48);
  }
}
