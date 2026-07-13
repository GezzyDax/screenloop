<script setup>
import {
  AlertTriangle,
  Download,
  Edit3,
  Info,
  Network,
  Plus,
  Radar,
  RefreshCcw,
  RotateCcw,
  Search,
  Server,
  SkipForward,
  Square,
  Trash2,
  Tv,
  Upload,
  Volume2,
  VolumeX,
  Wifi,
} from "@lucide/vue";
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
  const duration = Number(tv.current_media_duration_seconds || 0);
  return duration ? Math.min(elapsed, duration) : elapsed;
}

function playbackProgress(tv) {
  const duration = Number(tv.current_media_duration_seconds || 0);
  if (!duration) return 0;
  return Math.min(100, Math.round((playbackElapsed(tv) / duration) * 100));
}

function tvStateClass(tv) {
  if (tv.last_error) return "bad";
  if (tv.streaming || tv.online) return "ok";
  return "bad";
}

function shortUrl(value) {
  if (!value) return "-";
  try {
    const url = new URL(value);
    const leaf = url.pathname.split("/").filter(Boolean).pop();
    return `${url.host}${leaf ? `/${leaf}` : ""}`;
  } catch (_) {
    return String(value).replace(/^https?:\/\//, "").slice(0, 48);
  }
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
          <button class="ghost action-button" @click="scanTvs">
            <Search :size="17" />
            <span>{{ t("scanNetwork") }}</span>
          </button>
          <button class="ghost action-button" @click="exportTvs">
            <Download :size="17" />
            <span>{{ t("exportTvConfigs") }}</span>
          </button>
          <label class="file-button ghost">
            <Upload :size="17" />
            <span>{{ t("importTvConfigs") }}</span>
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
        <button type="submit" class="action-button">
          <Plus :size="17" />
          <span>{{ t("addTv") }}</span>
        </button>
      </form>

      <div v-if="scanDevices.length" class="list scan-list">
        <article v-for="device in scanDevices" :key="`${device.ip}-${device.control_url || device.location}`" class="list-item scan-device">
          <span>
            <strong>{{ device.friendly_name || device.ip }}</strong>
            <small>{{ device.ip }} · {{ device.profile || "generic_dlna" }} · {{ device.manufacturer || t("unknown") }} · {{ device.model_name || t("unknown") }}</small>
            <small class="mono">{{ device.control_url || device.location || "-" }}</small>
          </span>
          <button v-if="!device.configured" class="action-button" @click="addScannedTv(device)">
            <Plus :size="17" />
            <span>{{ t("addTv") }}</span>
          </button>
          <span v-else class="pill ok">{{ t("configured") }}</span>
        </article>
      </div>
    </div>

    <div class="tv-admin-grid">
      <article v-for="tv in status.tvs" :key="tv.id" class="panel tv-admin-card">
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

        <div v-if="canOperate" class="card-actions tv-actionbar">
          <button class="icon-button primary" :title="t('playNext')" :aria-label="t('playNext')" @click="command(tv, 'play_next')">
            <SkipForward :size="19" />
          </button>
          <button class="icon-button secondary" :title="t('stop')" :aria-label="t('stop')" @click="command(tv, 'stop')">
            <Square :size="18" />
          </button>
          <button class="icon-button ghost" :title="t('restart')" :aria-label="t('restart')" @click="command(tv, 'restart_playlist')">
            <RotateCcw :size="18" />
          </button>
          <button class="icon-button ghost" :title="t('rediscover')" :aria-label="t('rediscover')" @click="command(tv, 'rediscover')">
            <RefreshCcw :size="18" />
          </button>
          <button class="icon-button ghost" :title="tv.muted ? t('unmute') : t('mute')" :aria-label="tv.muted ? t('unmute') : t('mute')" @click="command(tv, tv.muted ? 'unmute' : 'mute')">
            <Volume2 v-if="tv.muted" :size="18" />
            <VolumeX v-else :size="18" />
          </button>
          <button class="icon-button ghost" :title="t('details')" :aria-label="t('details')" @click="selectTv(tv)">
            <Info :size="18" />
          </button>
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
            <strong class="mono" :title="tv.control_url || ''">{{ shortUrl(tv.control_url) }}</strong>
          </div>
          <div>
            <span>{{ t("renderingControlUrl") }}</span>
            <strong class="mono" :title="tv.rendering_control_url || ''">{{ shortUrl(tv.rendering_control_url) }}</strong>
          </div>
          <div class="row-actions wide">
            <button class="icon-button ghost" :title="t('edit')" :aria-label="t('edit')" @click="beginEditTv(tv)">
              <Edit3 :size="18" />
            </button>
            <button class="icon-button ghost" :title="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :aria-label="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" @click="toggleTvAutoplay(tv)">
              <RefreshCcw :size="18" />
            </button>
            <button class="icon-button ghost" :title="t('detect')" :aria-label="t('detect')" @click="detectTv(tv)">
              <Search :size="18" />
            </button>
            <button class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" @click="deleteTv(tv)">
              <Trash2 :size="18" />
            </button>
          </div>
        </div>
      </article>
      <div v-if="!status.tvs.length" class="empty">{{ t("noTvs") }}</div>
    </div>
  </section>
</template>
