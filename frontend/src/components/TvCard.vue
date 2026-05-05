<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

defineProps({
  tv: { type: Object, required: true },
});

const { t } = useI18n();
const { canOperate, command, statusClass } = useScreenloop();

function formatTime(value) {
  if (!value) return "-";
  return new Date(Number(value) * 1000).toLocaleString();
}

function healthReason(tv) {
  if (tv.last_error) return tv.last_error;
  if (!tv.ping_reachable) return t("reasonPingUnavailable");
  if (!tv.dlna_reachable) return t("reasonDlnaUnavailable");
  if (!tv.soap_ready) return t("reasonSoapUnavailable");
  if (tv.streaming) return t("reasonStreaming");
  if (tv.online) return t("reasonReady");
  return t("reasonWaitingDiscovery");
}

function commandText(tv) {
  if (!tv.last_command) return t("noCommands");
  const status = tv.last_command_status || "unknown";
  return `${tv.last_command} · ${status}`;
}

function eventText(tv) {
  if (!tv.last_event_type) return t("noEventsShort");
  return `${tv.last_event_type}: ${tv.last_event_message || "-"}`;
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
      <div><dt>{{ t("lastSeen") }}</dt><dd>{{ formatTime(tv.last_seen) }}</dd></div>
    </dl>
    <div class="tv-activity">
      <div>
        <span>{{ t("lastCommand") }}</span>
        <strong>{{ commandText(tv) }}</strong>
        <small>{{ formatTime(tv.last_command_finished_at || tv.last_command_started_at || tv.last_command_created_at) }}</small>
        <small v-if="tv.last_command_error" class="error">{{ tv.last_command_error }}</small>
      </div>
      <div>
        <span>{{ t("lastEvent") }}</span>
        <strong>{{ eventText(tv) }}</strong>
        <small>{{ formatTime(tv.last_event_created_at) }}</small>
      </div>
    </div>
    <div v-if="canOperate" class="card-actions">
      <button @click="command(tv, 'play_next')">{{ t("playNext") }}</button>
      <button class="secondary" @click="command(tv, 'stop')">{{ t("stop") }}</button>
      <button class="ghost" @click="command(tv, 'restart_playlist')">{{ t("restart") }}</button>
      <button class="ghost" @click="command(tv, tv.muted ? 'unmute' : 'mute')">{{ tv.muted ? t("unmute") : t("mute") }}</button>
    </div>
  </article>
</template>
