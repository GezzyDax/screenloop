<script setup>
import {
  AlertTriangle,
  Info,
  Network,
  Radar,
  RotateCcw,
  Server,
  SkipForward,
  Square,
  Tv,
  Volume2,
  VolumeX,
  Wifi,
} from "@lucide/vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatDuration, formatUnixTime } from "../utils/time";

defineProps({
  tv: { type: Object, required: true },
});

const { t } = useI18n();
const { canOperate, command, selectTv, statusClass } = useScreenloop();

const healthChecks = [
  { key: "ping_reachable", label: "ping", icon: Wifi },
  { key: "dlna_reachable", label: "dlna", icon: Network },
  { key: "soap_ready", label: "soap", icon: Server },
  { key: "streaming", label: "stream", icon: Radar },
];

function healthReason(tv) {
  if (tv.last_error) return tv.last_error;
  if (!tv.ping_reachable) return t("reasonPingUnavailable");
  if (!tv.dlna_reachable) return t("reasonDlnaUnavailable");
  if (!tv.soap_ready) return t("reasonSoapUnavailable");
  if (tv.streaming) return t("reasonStreaming");
  if (tv.online) return t("reasonReady");
  return t("reasonWaitingDiscovery");
}

function playbackElapsed(tv) {
  const startedAt = Number(tv.playback_started_at || 0);
  if (!startedAt || !tv.current_media_id) return 0;
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  const duration = playbackDuration(tv);
  return duration ? Math.min(elapsed, duration) : elapsed;
}

function playbackDuration(tv) {
  return Number(tv.current_media_duration_seconds || 0);
}

function playbackProgress(tv) {
  const duration = playbackDuration(tv);
  if (!duration) return 0;
  return Math.min(100, Math.round((playbackElapsed(tv) / duration) * 100));
}

function tvStateClass(tv) {
  if (tv.last_error) return "bad";
  if (tv.streaming || tv.online) return "ok";
  return "bad";
}
</script>

<template>
  <article class="tv-card">
    <div class="tv-head">
      <div class="tv-title">
        <span class="tv-device-icon" :class="tvStateClass(tv)">
          <Tv :size="19" />
        </span>
        <div>
          <h2>{{ tv.name }}</h2>
          <p>{{ tv.ip }} · {{ tv.profile }}</p>
        </div>
      </div>
      <span class="state" :class="tvStateClass(tv)">{{ tv.online ? "online" : "offline" }}</span>
    </div>
    <div class="tv-status-strip">
      <span class="playback-state" :class="statusClass(tv.playback_state)">{{ tv.playback_state || "UNKNOWN" }}</span>
      <span
        v-for="check in healthChecks"
        :key="check.key"
        class="health-dot"
        :class="statusClass(!!tv[check.key])"
        :title="check.label"
        :aria-label="check.label"
      >
        <component :is="check.icon" :size="15" />
      </span>
      <span v-if="tv.active_command_count" class="warn">{{ t("commandsQueued", { count: tv.active_command_count }) }}</span>
    </div>
    <p class="health-reason" :class="tv.last_error ? 'bad' : statusClass(!!tv.online)">
      <AlertTriangle v-if="tv.last_error" :size="17" />
      <Info v-else :size="17" />
      <span>{{ healthReason(tv) }}</span>
    </p>
    <dl>
      <div><dt>{{ t("playlist") }}</dt><dd>{{ tv.playlist_name || t("notAssigned") }}</dd></div>
      <div><dt>{{ t("now") }}</dt><dd>{{ tv.current_media_title || t("nothingStarted") }}</dd></div>
      <div><dt>{{ t("next") }}</dt><dd>{{ tv.next_media_title || t("playlistStart") }}</dd></div>
      <div><dt>{{ t("lastSeen") }}</dt><dd>{{ formatUnixTime(tv.last_seen) }}</dd></div>
    </dl>
    <div class="playback-panel">
      <div class="playback-line">
        <span>{{ t("playback") }}</span>
        <strong>{{ formatDuration(playbackElapsed(tv)) }} / {{ playbackDuration(tv) ? formatDuration(playbackDuration(tv)) : t("unknownDuration") }}</strong>
      </div>
      <div class="progress-track" :title="`${playbackProgress(tv)}%`">
        <span :style="{ width: `${playbackProgress(tv)}%` }"></span>
      </div>
      <div class="playback-meta">
        <span>{{ t("queueIndex", { index: tv.current_index ?? 0 }) }}</span>
        <span>{{ t("currentMediaId", { id: tv.current_media_id || '-' }) }}</span>
        <span>{{ t("nextMediaId", { id: tv.next_media_id || '-' }) }}</span>
      </div>
    </div>
    <div v-if="canOperate" class="card-actions tv-actionbar">
      <button class="icon-button ghost" :title="t('details')" :aria-label="t('details')" @click="selectTv(tv)">
        <Info :size="18" />
      </button>
      <button class="icon-button primary" :title="t('playNext')" :aria-label="t('playNext')" @click="command(tv, 'play_next')">
        <SkipForward :size="19" />
      </button>
      <button class="icon-button secondary" :title="t('stop')" :aria-label="t('stop')" @click="command(tv, 'stop')">
        <Square :size="18" />
      </button>
      <button class="icon-button ghost" :title="t('restart')" :aria-label="t('restart')" @click="command(tv, 'restart_playlist')">
        <RotateCcw :size="18" />
      </button>
      <button class="icon-button ghost" :title="tv.muted ? t('unmute') : t('mute')" :aria-label="tv.muted ? t('unmute') : t('mute')" @click="command(tv, tv.muted ? 'unmute' : 'mute')">
        <Volume2 v-if="tv.muted" :size="18" />
        <VolumeX v-else :size="18" />
      </button>
    </div>
  </article>
</template>
