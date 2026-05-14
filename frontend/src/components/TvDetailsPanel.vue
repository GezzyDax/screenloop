<script setup>
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatDuration, formatUnixTime } from "../utils/time";

const { t } = useI18n();
const { selectedTv, selectedTvEvents, status, tvProfiles, selectTv } = useScreenloop();

const profile = computed(() => {
  if (!selectedTv.value) return null;
  return tvProfiles.value[selectedTv.value.profile] || null;
});

function safeDetails(value) {
  if (!value) return "";
  return String(value).replace(/token=[^&\s]+/g, "token=...");
}

function commandText(tv) {
  if (!tv?.last_command) return t("noCommands");
  const status = tv.last_command_status || "unknown";
  return `${tv.last_command} · ${status}`;
}

function eventText(tv) {
  if (!tv?.last_event_type) return t("noEventsShort");
  return `${tv.last_event_type}: ${tv.last_event_message || "-"}`;
}

function lastStreamText(tv) {
  if (!tv?.last_stream_event_type) return t("noStreamEvents");
  return `${tv.last_stream_event_type}: ${tv.last_stream_event_message || "-"}`;
}

function profileLine() {
  const ffmpeg = profile.value?.ffmpeg || {};
  return [
    ffmpeg.container,
    ffmpeg.video_codec,
    ffmpeg.h264_profile ? `H.264 ${ffmpeg.h264_profile}@${ffmpeg.h264_level || "-"}` : "",
    ffmpeg.audio_codec,
    ffmpeg.maxrate,
  ].filter(Boolean).join(" · ") || "-";
}
</script>

<template>
  <section class="panel tv-details-panel">
    <div class="section-head">
      <div>
        <h2>{{ t("tvDetails") }}</h2>
        <p class="muted">{{ t("tvDetailsHint") }}</p>
      </div>
      <select :value="selectedTv?.id || ''" @change="selectTv(status.tvs.find((tv) => tv.id === Number($event.target.value)) || null)">
        <option value="">{{ t("selectTv") }}</option>
        <option v-for="tv in status.tvs" :key="tv.id" :value="tv.id">{{ tv.name }} · {{ tv.ip }}</option>
      </select>
    </div>

    <div v-if="selectedTv" class="details-grid">
      <article>
        <h3>{{ t("device") }}</h3>
        <div class="facts-list">
          <div class="fact-line"><span>{{ t("name") }}</span><strong>{{ selectedTv.name }}</strong></div>
          <div class="fact-line"><span>{{ t("ip") }}</span><strong class="mono">{{ selectedTv.ip }}</strong></div>
          <div class="fact-line"><span>{{ t("profile") }}</span><strong>{{ selectedTv.profile }}</strong></div>
          <div class="fact-line"><span>{{ t("controlUrl") }}</span><strong class="mono">{{ selectedTv.control_url || "-" }}</strong></div>
          <div class="fact-line"><span>{{ t("renderingControlUrl") }}</span><strong class="mono">{{ selectedTv.rendering_control_url || "-" }}</strong></div>
        </div>
      </article>

      <article>
        <h3>{{ t("playback") }}</h3>
        <div class="facts-list">
          <div class="fact-line"><span>{{ t("playlist") }}</span><strong>{{ selectedTv.playlist_name || t("notAssigned") }}</strong></div>
          <div class="fact-line"><span>{{ t("now") }}</span><strong>{{ selectedTv.current_media_title || t("nothingStarted") }}</strong></div>
          <div class="fact-line"><span>{{ t("next") }}</span><strong>{{ selectedTv.next_media_title || t("playlistStart") }}</strong></div>
          <div class="fact-line"><span>{{ t("duration") }}</span><strong>{{ selectedTv.current_media_duration_seconds ? formatDuration(selectedTv.current_media_duration_seconds) : t("unknownDuration") }}</strong></div>
          <div class="fact-line"><span>{{ t("lastError") }}</span><strong :class="selectedTv.last_error ? 'bad' : ''">{{ selectedTv.last_error || "-" }}</strong></div>
        </div>
      </article>

      <article>
        <h3>{{ t("profile") }}</h3>
        <div class="facts-list">
          <div class="fact-line"><span>{{ t("profileName") }}</span><strong>{{ profile?.name || selectedTv.profile }}</strong></div>
          <div class="fact-line"><span>{{ t("profileEncoding") }}</span><strong>{{ profileLine() }}</strong></div>
          <div class="fact-line"><span>{{ t("mimeType") }}</span><strong>{{ profile?.mime_type || "video/mp4" }}</strong></div>
          <div class="fact-line"><span>{{ t("dlnaProtocolInfo") }}</span><strong class="mono">{{ profile?.dlna_protocol_info || "-" }}</strong></div>
        </div>
      </article>

      <article>
        <h3>{{ t("activity") }}</h3>
        <div class="facts-list">
          <div class="fact-line"><span>{{ t("lastCommand") }}</span><strong>{{ commandText(selectedTv) }}</strong></div>
          <div class="fact-line"><span>{{ t("time") }}</span><strong>{{ formatUnixTime(selectedTv.last_command_finished_at || selectedTv.last_command_started_at || selectedTv.last_command_created_at) }}</strong></div>
          <div class="fact-line"><span>{{ t("lastEvent") }}</span><strong>{{ eventText(selectedTv) }}</strong></div>
          <div class="fact-line"><span>{{ t("lastStreamEvent") }}</span><strong>{{ lastStreamText(selectedTv) }}</strong></div>
          <div class="fact-line"><span>{{ t("details") }}</span><strong class="mono">{{ safeDetails(selectedTv.last_stream_event_details) || "-" }}</strong></div>
        </div>
      </article>
    </div>

    <div v-if="selectedTv" class="table tv-events-table">
      <div class="table-row head"><span>{{ t("type") }}</span><span>{{ t("message") }}</span><span>{{ t("details") }}</span><span>{{ t("time") }}</span></div>
      <div v-for="event in selectedTvEvents" :key="event.id" class="table-row">
        <span><strong>{{ event.event_type }}</strong></span>
        <span>{{ event.message || "-" }}</span>
        <span class="mono">{{ safeDetails(event.details) || "-" }}</span>
        <span>{{ formatUnixTime(event.created_at) }}</span>
      </div>
      <div v-if="!selectedTvEvents.length" class="empty">{{ t("noTvEvents") }}</div>
    </div>

    <div v-else class="empty">{{ t("selectTvHint") }}</div>
  </section>
</template>
