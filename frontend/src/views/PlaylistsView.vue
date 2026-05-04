<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  addPlaylistMedia,
  canOperate,
  createPlaylist,
  deletePlaylist,
  isAdmin,
  loadPlaylist,
  movePlaylistItem,
  playlistForm,
  playlistItems,
  readyMedia,
  removePlaylistItem,
  selectedPlaylist,
  selectedPlaylistId,
  status,
} = useScreenloop();
</script>

<template>
  <section class="split-panels">
    <div class="panel">
      <div class="section-head">
        <h2>{{ t("playlists") }}</h2>
      </div>
      <form v-if="canOperate" class="inline-form" @submit.prevent="createPlaylist">
        <input v-model="playlistForm.name" :placeholder="t('newPlaylistName')" />
        <button type="submit">{{ t("create") }}</button>
      </form>
      <div class="list">
        <article v-for="playlist in status.playlists" :key="playlist.id" class="list-item">
          <span><strong>{{ playlist.name }}</strong><small>{{ t("items", { count: playlist.item_count }) }}</small></span>
          <span class="row-actions">
            <button class="ghost" @click="loadPlaylist(playlist.id)">{{ t("open") }}</button>
            <button v-if="isAdmin" class="danger" @click="deletePlaylist(playlist)">{{ t("delete") }}</button>
          </span>
        </article>
      </div>
    </div>
    <div class="panel">
      <h2>{{ selectedPlaylist?.name || t("playlistItems") }}</h2>
      <div v-if="selectedPlaylistId && canOperate" class="inline-form">
        <select @change="addPlaylistMedia($event.target.value); $event.target.value = ''">
          <option value="">{{ t("addReadyMedia") }}</option>
          <option v-for="item in readyMedia" :key="item.id" :value="item.id">{{ item.title }}</option>
        </select>
      </div>
      <div v-if="playlistItems.length" class="list">
        <article v-for="item in playlistItems" :key="item.id" class="list-item">
          <span><strong>{{ item.title }}</strong><small>#{{ item.position }} · {{ t("mediaId", { id: item.media_id }) }}</small></span>
          <span v-if="canOperate" class="row-actions">
            <button class="ghost" @click="movePlaylistItem(item, 'up')">{{ t("up") }}</button>
            <button class="ghost" @click="movePlaylistItem(item, 'down')">{{ t("down") }}</button>
            <button class="danger" @click="removePlaylistItem(item)">{{ t("remove") }}</button>
          </span>
        </article>
      </div>
      <div v-else class="empty">{{ t("openPlaylistHint") }}</div>
    </div>
  </section>
</template>
