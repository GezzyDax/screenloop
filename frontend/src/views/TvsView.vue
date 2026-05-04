<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  addScannedTv,
  canOperate,
  command,
  createTv,
  deleteTv,
  detectTv,
  isAdmin,
  scanDevices,
  scanTvs,
  status,
  statusClass,
  tvForm,
  tvProfiles,
  updateTvPlaylist,
} = useScreenloop();
</script>

<template>
  <section class="stack">
    <div v-if="isAdmin" class="panel">
      <div class="section-head">
        <h2>{{ t("addTv") }}</h2>
        <button class="ghost" @click="scanTvs">{{ t("scanNetwork") }}</button>
      </div>
      <form class="form-grid" @submit.prevent="createTv">
        <label>{{ t("name") }}<input v-model="tvForm.name" placeholder="Lobby Samsung" required /></label>
        <label>{{ t("ip") }}<input v-model="tvForm.ip" placeholder="192.168.1.50" required /></label>
        <label>{{ t("profile") }}
          <select v-model="tvForm.profile">
            <option v-for="(_, key) in tvProfiles" :key="key" :value="key">{{ key }}</option>
          </select>
        </label>
        <button type="submit">{{ t("addTv") }}</button>
      </form>
      <div v-if="scanDevices.length" class="list scan-list">
        <article v-for="device in scanDevices" :key="device.ip" class="list-item">
          <span>
            <strong>{{ device.friendly_name || device.ip }}</strong>
            <small>{{ device.ip }} · {{ device.manufacturer || t("unknown") }} · {{ device.model_name || t("unknown") }}</small>
          </span>
          <button v-if="!device.configured" @click="addScannedTv(device)">{{ t("addTv") }}</button>
          <span v-else class="pill ok">{{ t("configured") }}</span>
        </article>
      </div>
    </div>

    <div class="panel">
      <h2>{{ t("configuredTvs") }}</h2>
      <div class="table tv-table">
        <div class="table-row head"><span>{{ t("name") }}</span><span>{{ t("status") }}</span><span>{{ t("playlist") }}</span><span>{{ t("actions") }}</span></div>
        <div v-for="tv in status.tvs" :key="tv.id" class="table-row">
          <span><strong>{{ tv.name }}</strong><small>{{ tv.ip }} · {{ tv.profile }}</small></span>
          <span><b :class="statusClass(!!tv.online)">{{ tv.online ? "online" : "offline" }}</b><small>{{ tv.playback_state || "UNKNOWN" }}</small></span>
          <span>
            <select :value="tv.active_playlist_id || ''" :disabled="!isAdmin" @change="updateTvPlaylist(tv, $event.target.value)">
              <option value="">{{ t("noPlaylist") }}</option>
              <option v-for="playlist in status.playlists" :key="playlist.id" :value="playlist.id">{{ playlist.name }}</option>
            </select>
          </span>
          <span class="row-actions">
            <button v-if="canOperate" @click="command(tv, 'play_next')">{{ t("playNext") }}</button>
            <button v-if="isAdmin" class="ghost" @click="detectTv(tv)">{{ t("detect") }}</button>
            <button v-if="isAdmin" class="danger" @click="deleteTv(tv)">{{ t("delete") }}</button>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
