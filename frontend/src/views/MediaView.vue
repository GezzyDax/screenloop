<script setup>
import { Archive, RotateCcw, Search, Trash2, Upload, Volume2, VolumeX } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";

const { t, tOr } = useI18n();
const {
  busy,
  canOperate,
  deleteMedia,
  isAdmin,
  isPending,
  onUploadChange,
  status,
  statusClass,
  toggleCompression,
  toggleSilent,
  uploadFile,
  uploadMedia,
  uploadProgress,
} = useScreenloop();

const query = ref("");

const filteredMedia = computed(() => {
  const needle = query.value.trim().toLowerCase();
  if (!needle) return status.value.media;
  return status.value.media.filter(
    (item) => item.title.toLowerCase().includes(needle) || (item.original_name || "").toLowerCase().includes(needle),
  );
});
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <div>
        <h2>{{ t("mediaLibrary") }}</h2>
        <p class="muted">{{ t("readyMedia") }}: {{ status.media.filter((item) => item.status === "ready").length }}</p>
      </div>
      <form v-if="canOperate" class="upload-form toolbar" @submit.prevent="uploadMedia">
        <label class="file-button ghost">
          <Upload :size="14" />
          <span>{{ uploadFile?.name || t("chooseFile") }}</span>
          <input type="file" accept="video/*" @change="onUploadChange" />
        </label>
        <button type="submit" class="action-button" :disabled="busy || !uploadFile">
          <Upload :size="14" />
          <span>{{ busy ? t("uploading") : t("upload") }}</span>
        </button>
      </form>
    </div>
    <div v-if="uploadProgress !== null" class="upload-progress">
      <div class="progress-track">
        <span :style="{ width: `${uploadProgress}%` }"></span>
      </div>
      <span class="muted">{{ uploadProgress }}%</span>
    </div>
    <label class="search-field">
      <Search :size="14" />
      <input v-model="query" type="search" :placeholder="t('searchPlaceholder')" :aria-label="t('searchPlaceholder')" />
    </label>
    <div class="table media-table">
      <div class="table-row head"><span>{{ t("name") }}</span><span>{{ t("status") }}</span><span>{{ t("size") }}</span><span>{{ t("audio") }}</span><span>{{ t("compression") }}</span><span>{{ t("actions") }}</span></div>
      <div v-for="item in filteredMedia" :key="item.id" class="table-row">
        <span><strong>{{ item.title }}</strong><small>{{ item.original_name }}</small></span>
        <span><b class="status-pill" :class="statusClass(item.status)">{{ tOr(`mediaStatus_${item.status}`, item.status) }}</b></span>
        <span class="mono">{{ formatBytes(item.size) }}</span>
        <span class="inline-status">
          <VolumeX v-if="item.silent" :size="13" />
          <Volume2 v-else :size="13" />
          {{ item.silent ? t("silent") : t("original") }}
        </span>
        <span class="inline-status">
          <Archive :size="13" />
          {{ item.compressed ? t("smaller") : t("standard") }}
        </span>
        <span class="row-actions">
          <button v-if="canOperate" class="icon-button ghost" :title="item.silent ? t('restoreAudio') : t('silentCopy')" :aria-label="item.silent ? t('restoreAudio') : t('silentCopy')" :disabled="isPending(`media:${item.id}`)" @click="toggleSilent(item)">
            <Volume2 v-if="item.silent" :size="15" />
            <VolumeX v-else :size="15" />
          </button>
          <button v-if="canOperate" class="icon-button ghost" :title="item.compressed ? t('standardCopy') : t('smallerCopy')" :aria-label="item.compressed ? t('standardCopy') : t('smallerCopy')" :disabled="isPending(`media:${item.id}`)" @click="toggleCompression(item)">
            <RotateCcw v-if="item.compressed" :size="15" />
            <Archive v-else :size="15" />
          </button>
          <button v-if="isAdmin" class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" :disabled="isPending(`media:${item.id}`)" @click="deleteMedia(item)">
            <Trash2 :size="15" />
          </button>
        </span>
      </div>
      <div v-if="!filteredMedia.length" class="empty">{{ t("emptyMedia") }}</div>
    </div>
  </section>
</template>
