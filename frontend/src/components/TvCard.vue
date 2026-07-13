<script setup>
import {
  AlertTriangle,
  Info,
  RefreshCcw,
  RotateCcw,
  SkipForward,
  Square,
  Tv,
  Volume2,
  VolumeX,
} from "@lucide/vue";
import {
  healthChecks,
  healthReason,
  onlineLabel,
  playbackDuration,
  playbackElapsed,
  playbackProgress,
  stateLabel,
  tvStateClass,
} from "../composables/tvCard";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatDuration, formatUnixTime } from "../utils/time";

const props = defineProps({
  tv: { type: Object, required: true },
  variant: { type: String, default: "dashboard" },
});

const { t } = useI18n();
const { canOperate, command, isAdmin, isPending, selectTv, statusClass } = useScreenloop();

const isAdminVariant = props.variant === "admin";
</script>

<template>
  <article :class="isAdminVariant ? 'panel tv-admin-card' : 'tv-card'">
    <div class="tv-head">
      <div class="tv-title">
        <span class="tv-device-icon" :class="tvStateClass(tv)">
          <Tv :size="16" />
        </span>
        <div>
          <h2>{{ tv.name }}</h2>
          <p>{{ tv.ip }} · {{ tv.profile }}<template v-if="tv.node_name"> · {{ tv.node_name }}</template></p>
        </div>
      </div>
      <span class="state" :class="tvStateClass(tv)">{{ onlineLabel(tv) }}</span>
    </div>
    <div class="tv-status-strip">
      <span class="playback-state" :class="statusClass(tv.playback_state)">{{ stateLabel(tv.playback_state) }}</span>
      <span
        v-for="check in healthChecks"
        :key="check.key"
        class="health-dot"
        :class="statusClass(!!tv[check.key])"
        :title="t(check.labelKey)"
        :aria-label="t(check.labelKey)"
      >
        <component :is="check.icon" :size="13" />
      </span>
      <span v-if="tv.active_command_count" class="warn">{{ t("commandsQueued", { count: tv.active_command_count }) }}</span>
    </div>
    <p class="health-reason" :class="tv.last_error ? 'bad' : statusClass(!!tv.online)">
      <AlertTriangle v-if="tv.last_error" :size="14" />
      <Info v-else :size="14" />
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
      <button
        class="icon-button primary"
        :title="t('playNext')"
        :aria-label="t('playNext')"
        :disabled="isPending(`command:${tv.id}`)"
        @click="command(tv, 'play_next')"
      >
        <SkipForward :size="16" />
      </button>
      <button
        class="icon-button secondary"
        :title="t('stop')"
        :aria-label="t('stop')"
        :disabled="isPending(`command:${tv.id}`)"
        @click="command(tv, 'stop')"
      >
        <Square :size="15" />
      </button>
      <button
        class="icon-button ghost"
        :title="t('restart')"
        :aria-label="t('restart')"
        :disabled="isPending(`command:${tv.id}`)"
        @click="command(tv, 'restart_playlist')"
      >
        <RotateCcw :size="15" />
      </button>
      <button
        v-if="isAdmin"
        class="icon-button ghost"
        :title="t('rediscover')"
        :aria-label="t('rediscover')"
        :disabled="isPending(`command:${tv.id}`)"
        @click="command(tv, 'rediscover')"
      >
        <RefreshCcw :size="15" />
      </button>
      <button
        class="icon-button ghost"
        :title="tv.muted ? t('unmute') : t('mute')"
        :aria-label="tv.muted ? t('unmute') : t('mute')"
        :disabled="isPending(`command:${tv.id}`)"
        @click="command(tv, tv.muted ? 'unmute' : 'mute')"
      >
        <Volume2 v-if="tv.muted" :size="15" />
        <VolumeX v-else :size="15" />
      </button>
      <button class="icon-button ghost" :title="t('details')" :aria-label="t('details')" @click="selectTv(tv)">
        <Info :size="15" />
      </button>
    </div>
    <slot name="footer" />
  </article>
</template>
