<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

defineProps({
  tv: { type: Object, required: true },
});

const { t } = useI18n();
const { canOperate, command, statusClass } = useScreenloop();
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
    </div>
    <dl>
      <div><dt>{{ t("playlist") }}</dt><dd>{{ tv.playlist_name || t("notAssigned") }}</dd></div>
      <div><dt>{{ t("now") }}</dt><dd>{{ tv.current_media_title || t("nothingStarted") }}</dd></div>
      <div><dt>{{ t("next") }}</dt><dd>{{ tv.next_media_title || t("playlistStart") }}</dd></div>
    </dl>
    <p v-if="tv.last_error" class="error">{{ tv.last_error }}</p>
    <div v-if="canOperate" class="card-actions">
      <button @click="command(tv, 'play_next')">{{ t("playNext") }}</button>
      <button class="secondary" @click="command(tv, 'stop')">{{ t("stop") }}</button>
      <button class="ghost" @click="command(tv, 'restart_playlist')">{{ t("restart") }}</button>
      <button class="ghost" @click="command(tv, tv.muted ? 'unmute' : 'mute')">{{ tv.muted ? t("unmute") : t("mute") }}</button>
    </div>
  </article>
</template>
