<script setup>
import { ChevronDown, ChevronUp, FolderOpen, GripVertical, Plus, Trash2, X } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  addPlaylistMedia,
  canOperate,
  createPlaylist,
  deletePlaylist,
  isAdmin,
  isPending,
  loadPlaylist,
  movePlaylistItem,
  movePlaylistItemTo,
  playlistForm,
  playlistItems,
  readyMedia,
  removePlaylistItem,
  selectedPlaylist,
  selectedPlaylistId,
  status,
} = useScreenloop();

const draggedItemId = ref(null);
const dropTargetIndex = ref(null);

function onDragStart(item) {
  draggedItemId.value = item.id;
}

function onDragOver(index) {
  dropTargetIndex.value = index;
}

function onDrop(index) {
  if (draggedItemId.value !== null) {
    movePlaylistItemTo(draggedItemId.value, index);
  }
  draggedItemId.value = null;
  dropTargetIndex.value = null;
}

function onDragEnd() {
  draggedItemId.value = null;
  dropTargetIndex.value = null;
}
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
          <Plus :size="14" />
          <span>{{ t("create") }}</span>
        </button>
      </form>
      <div class="list">
        <article v-for="playlist in status.playlists" :key="playlist.id" class="list-item" :class="{ selected: playlist.id === selectedPlaylistId }">
          <span><strong>{{ playlist.name }}</strong><small>{{ t("items", { count: playlist.item_count }) }}</small></span>
          <span class="row-actions">
            <button class="icon-button ghost" :title="t('open')" :aria-label="t('open')" @click="loadPlaylist(playlist.id)">
              <FolderOpen :size="15" />
            </button>
            <button v-if="isAdmin" class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" @click="deletePlaylist(playlist)">
              <Trash2 :size="15" />
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
        <article
          v-for="(item, index) in playlistItems"
          :key="item.id"
          class="list-item"
          :class="{ 'drop-target': dropTargetIndex === index, dragging: draggedItemId === item.id }"
          :draggable="canOperate"
          @dragstart="onDragStart(item)"
          @dragover.prevent="onDragOver(index)"
          @drop.prevent="onDrop(index)"
          @dragend="onDragEnd"
        >
          <span class="drag-item">
            <GripVertical v-if="canOperate" :size="14" class="drag-handle" />
            <span><strong>{{ item.title }}</strong><small>#{{ item.position }} · {{ t("mediaId", { id: item.media_id }) }}</small></span>
          </span>
          <span v-if="canOperate" class="row-actions">
            <button class="icon-button ghost" :title="t('up')" :aria-label="t('up')" :disabled="isPending(`playlist-item:${item.id}`)" @click="movePlaylistItem(item, 'up')">
              <ChevronUp :size="15" />
            </button>
            <button class="icon-button ghost" :title="t('down')" :aria-label="t('down')" :disabled="isPending(`playlist-item:${item.id}`)" @click="movePlaylistItem(item, 'down')">
              <ChevronDown :size="15" />
            </button>
            <button class="icon-button danger" :title="t('remove')" :aria-label="t('remove')" :disabled="isPending(`playlist-item:${item.id}`)" @click="removePlaylistItem(item)">
              <X :size="15" />
            </button>
          </span>
        </article>
      </div>
      <div v-else class="empty">{{ t("openPlaylistHint") }}</div>
    </div>
  </section>
</template>
