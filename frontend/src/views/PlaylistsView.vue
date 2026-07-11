<script setup>
import { ChevronDown, ChevronUp, FolderOpen, Plus, Trash2, X } from "@lucide/vue";
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
        <button type="submit" class="action-button">
          <Plus :size="17" />
          <span>{{ t("create") }}</span>
        </button>
      </form>
      <div class="list">
        <article v-for="playlist in status.playlists" :key="playlist.id" class="list-item" :class="{ selected: playlist.id === selectedPlaylistId }">
          <span><strong>{{ playlist.name }}</strong><small>{{ t("items", { count: playlist.item_count }) }}</small></span>
          <span class="row-actions">
            <button class="icon-button ghost" :title="t('open')" :aria-label="t('open')" @click="loadPlaylist(playlist.id)">
              <FolderOpen :size="18" />
            </button>
            <button v-if="isAdmin" class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" @click="deletePlaylist(playlist)">
              <Trash2 :size="18" />
            </button>
          </span>
        </article>
        <div v-if="!status.playlists.length" class="empty">{{ t("emptyPlaylists") }}</div>
      </div>
    </div>
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ selectedPlaylist?.name || t("playlistItems") }}</h2>
          <p class="muted">{{ selectedPlaylistId ? t("items", { count: playlistItems.length }) : t("openPlaylistHint") }}</p>
        </div>
      </div>
      <div v-if="selectedPlaylistId && canOperate" class="inline-form toolbar">
        <select @change="addPlaylistMedia($event.target.value); $event.target.value = ''">
          <option value="">{{ t("addReadyMedia") }}</option>
          <option v-for="item in readyMedia" :key="item.id" :value="item.id">{{ item.title }}</option>
        </select>
      </div>
      <div v-if="playlistItems.length" class="list">
        <article v-for="item in playlistItems" :key="item.id" class="list-item">
          <span><strong>{{ item.title }}</strong><small>#{{ item.position }} · {{ t("mediaId", { id: item.media_id }) }}</small></span>
          <span v-if="canOperate" class="row-actions">
            <button class="icon-button ghost" :title="t('up')" :aria-label="t('up')" @click="movePlaylistItem(item, 'up')">
              <ChevronUp :size="18" />
            </button>
            <button class="icon-button ghost" :title="t('down')" :aria-label="t('down')" @click="movePlaylistItem(item, 'down')">
              <ChevronDown :size="18" />
            </button>
            <button class="icon-button danger" :title="t('remove')" :aria-label="t('remove')" @click="removePlaylistItem(item)">
              <X :size="18" />
            </button>
          </span>
        </article>
      </div>
      <div v-else class="empty">{{ t("openPlaylistHint") }}</div>
    </div>
  </section>
</template>
