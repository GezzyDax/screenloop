<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatDuration, formatUnixTime } from "../utils/time";

const { t } = useI18n();
const {
  addScannedTv,
  beginEditTv,
  cancelEditTv,
  canOperate,
  command,
  createTv,
  deleteTv,
  detectTv,
  exportTvs,
  importTvsFile,
  isAdmin,
  saveTv,
  scanDevices,
  scanTvs,
  selectTv,
  status,
  statusClass,
  toggleTvAutoplay,
  tvEditForms,
  tvForm,
  tvProfiles,
  updateTvPlaylist,
} = useScreenloop();

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
  const duration = Number(tv.current_media_duration_seconds || 0);
  return duration ? Math.min(elapsed, duration) : elapsed;
}

function playbackProgress(tv) {
  const duration = Number(tv.current_media_duration_seconds || 0);
  if (!duration) return 0;
  return Math.min(100, Math.round((playbackElapsed(tv) / duration) * 100));
}
</script>

<template>
  <section class="stack">
    <div v-if="isAdmin" class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("tvManagement") }}</h2>
          <p class="muted">{{ t("configuredTvs") }}</p>
        </div>
        <div class="top-actions">
          <button class="ghost" @click="scanTvs">{{ t("scanNetwork") }}</button>
          <button class="ghost" @click="exportTvs">{{ t("exportTvConfigs") }}</button>
          <label class="file-button ghost">
            {{ t("importTvConfigs") }}
            <input type="file" accept="application/json,.json" @change="importTvsFile" />
          </label>
        </div>
      </div>

      <form class="form-grid tv-create-form" @submit.prevent="createTv">
        <label>{{ t("name") }}<input v-model="tvForm.name" :placeholder="t('tvNamePlaceholder')" required /></label>
        <label>{{ t("ip") }}<input v-model="tvForm.ip" placeholder="192.168.1.50" required /></label>
        <label>{{ t("profile") }}
          <select v-model="tvForm.profile">
            <option v-for="(_, key) in tvProfiles" :key="key" :value="key">{{ key }}</option>
          </select>
        </label>
        <button type="submit">{{ t("addTv") }}</button>
      </form>

      <div v-if="scanDevices.length" class="list scan-list">
        <article v-for="device in scanDevices" :key="`${device.ip}-${device.control_url || device.location}`" class="list-item scan-device">
          <span>
            <strong>{{ device.friendly_name || device.ip }}</strong>
            <small>{{ device.ip }} · {{ device.profile || "generic_dlna" }} · {{ device.manufacturer || t("unknown") }} · {{ device.model_name || t("unknown") }}</small>
            <small class="mono">{{ device.control_url || device.location || "-" }}</small>
          </span>
          <button v-if="!device.configured" @click="addScannedTv(device)">{{ t("addTv") }}</button>
          <span v-else class="pill ok">{{ t("configured") }}</span>
        </article>
      </div>
    </div>

    <div class="tv-admin-grid">
      <article v-for="tv in status.tvs" :key="tv.id" class="panel tv-admin-card">
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
            <strong>{{ formatDuration(playbackElapsed(tv)) }} / {{ tv.current_media_duration_seconds ? formatDuration(tv.current_media_duration_seconds) : t("unknownDuration") }}</strong>
          </div>
          <div class="progress-track" :title="`${playbackProgress(tv)}%`">
            <span :style="{ width: `${playbackProgress(tv)}%` }"></span>
          </div>
          <div class="playback-meta">
            <span>{{ t("queueIndex", { index: tv.current_index ?? 0 }) }}</span>
            <span>{{ t("currentMediaId", { id: tv.current_media_id || "-" }) }}</span>
            <span>{{ t("nextMediaId", { id: tv.next_media_id || "-" }) }}</span>
          </div>
        </div>

        <div v-if="canOperate" class="card-actions">
          <button @click="command(tv, 'play_next')">{{ t("playNext") }}</button>
          <button class="secondary" @click="command(tv, 'stop')">{{ t("stop") }}</button>
          <button class="ghost" @click="command(tv, 'restart_playlist')">{{ t("restart") }}</button>
          <button class="ghost" @click="command(tv, 'rediscover')">{{ t("rediscover") }}</button>
          <button class="ghost" @click="command(tv, tv.muted ? 'unmute' : 'mute')">{{ tv.muted ? t("unmute") : t("mute") }}</button>
          <button class="ghost" @click="selectTv(tv)">{{ t("details") }}</button>
        </div>

        <form v-if="isAdmin && tvEditForms[tv.id]" class="tv-edit-form" @submit.prevent="saveTv(tv)">
          <label>{{ t("name") }}<input v-model="tvEditForms[tv.id].name" required /></label>
          <label>{{ t("ip") }}<input v-model="tvEditForms[tv.id].ip" required /></label>
          <label>{{ t("profile") }}
            <select v-model="tvEditForms[tv.id].profile">
              <option v-for="(_, key) in tvProfiles" :key="key" :value="key">{{ key }}</option>
            </select>
          </label>
          <label>{{ t("playlist") }}
            <select v-model="tvEditForms[tv.id].playlist_id">
              <option value="">{{ t("noPlaylist") }}</option>
              <option v-for="playlist in status.playlists" :key="playlist.id" :value="playlist.id">{{ playlist.name }}</option>
            </select>
          </label>
          <label class="check-label"><input v-model="tvEditForms[tv.id].autoplay" type="checkbox" /> {{ t("autoplay") }}</label>
          <label class="wide">{{ t("controlUrl") }}<input v-model="tvEditForms[tv.id].control_url" placeholder="http://TV-IP:7676/smp_24_" /></label>
          <div class="row-actions wide">
            <button type="submit">{{ t("save") }}</button>
            <button type="button" class="ghost" @click="cancelEditTv(tv)">{{ t("cancel") }}</button>
            <button type="button" class="danger" @click="deleteTv(tv)">{{ t("delete") }}</button>
          </div>
        </form>

        <div v-else-if="isAdmin" class="tv-config-strip">
          <div>
            <span>{{ t("autoplay") }}</span>
            <strong>{{ tv.autoplay ? t("enabled") : t("disabled") }}</strong>
          </div>
          <div>
            <span>{{ t("controlUrl") }}</span>
            <strong class="mono">{{ tv.control_url || "-" }}</strong>
          </div>
          <div>
            <span>{{ t("renderingControlUrl") }}</span>
            <strong class="mono">{{ tv.rendering_control_url || "-" }}</strong>
          </div>
          <div class="row-actions wide">
            <button class="ghost" @click="beginEditTv(tv)">{{ t("edit") }}</button>
            <button class="ghost" @click="toggleTvAutoplay(tv)">{{ tv.autoplay ? t("disableAutoplay") : t("enableAutoplay") }}</button>
            <button class="ghost" @click="detectTv(tv)">{{ t("detect") }}</button>
            <button class="danger" @click="deleteTv(tv)">{{ t("delete") }}</button>
          </div>
        </div>
      </article>
      <div v-if="!status.tvs.length" class="empty">{{ t("noTvs") }}</div>
    </div>
  </section>
</template>
