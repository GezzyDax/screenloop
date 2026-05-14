<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatDuration, formatUnixTime } from "../utils/time";

defineProps({
  tv: { type: Object, required: true },
});

const { t } = useI18n();
const { canOperate, command, selectTv, statusClass } = useScreenloop();

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

</script>

<template>
  <article class="tv-card">
    <div class="tv-head">
      <div>
        <h2>{{ tv.name }}</h2>
        <p>{{ tv.ip }} · {{ tv.profile }}</p>
      </div>
      <span class="state" :class="statusClass(!!tv.online)">{{ tv.online ? "online" : "offline" }}</span>
    </div>
    <div class="status-row">
      <span :class="statusClass(tv.playback_state)">{{ tv.playback_state || "UNKNOWN" }}</span>
      <span :class="statusClass(!!tv.ping_reachable)">ping</span>
      <span :class="statusClass(!!tv.dlna_reachable)">dlna</span>
      <span :class="statusClass(!!tv.soap_ready)">soap</span>
      <span :class="statusClass(!!tv.streaming)">stream</span>
      <span v-if="tv.active_command_count" class="warn">{{ t("commandsQueued", { count: tv.active_command_count }) }}</span>
    </div>
    <p class="health-reason" :class="tv.last_error ? 'bad' : statusClass(!!tv.online)">{{ healthReason(tv) }}</p>
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
    <div v-if="canOperate" class="card-actions">
      <button class="ghost" @click="selectTv(tv)">{{ t("details") }}</button>
      <button @click="command(tv, 'play_next')">{{ t("playNext") }}</button>
      <button class="secondary" @click="command(tv, 'stop')">{{ t("stop") }}</button>
      <button class="ghost" @click="command(tv, 'restart_playlist')">{{ t("restart") }}</button>
      <button class="ghost" @click="command(tv, tv.muted ? 'unmute' : 'mute')">{{ tv.muted ? t("unmute") : t("mute") }}</button>
    </div>
  </article>
</template>
