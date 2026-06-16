<script setup>
import { Archive, RotateCcw, Trash2, Upload, Volume2, VolumeX } from "@lucide/vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";

const { t } = useI18n();
const {
  busy,
  canOperate,
  deleteMedia,
  isAdmin,
  onUploadChange,
  status,
  statusClass,
  toggleCompression,
  toggleSilent,
  uploadFile,
  uploadMedia,
} = useScreenloop();
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
          <Upload :size="17" />
          <span>{{ uploadFile?.name || t("upload") }}</span>
          <input type="file" accept="video/*" @change="onUploadChange" />
        </label>
        <button type="submit" class="action-button" :disabled="busy || !uploadFile">
          <Upload :size="17" />
          <span>{{ busy ? t("uploading") : t("upload") }}</span>
        </button>
      </form>
    </div>
    <div class="table media-table">
      <div class="table-row head"><span>{{ t("name") }}</span><span>{{ t("status") }}</span><span>{{ t("size") }}</span><span>{{ t("audio") }}</span><span>{{ t("compression") }}</span><span>{{ t("actions") }}</span></div>
      <div v-for="item in status.media" :key="item.id" class="table-row">
        <span><strong>{{ item.title }}</strong><small>{{ item.original_name }}</small></span>
        <span><b class="status-pill" :class="statusClass(item.status)">{{ item.status }}</b></span>
        <span class="mono">{{ formatBytes(item.size) }}</span>
        <span class="inline-status">
          <VolumeX v-if="item.silent" :size="15" />
          <Volume2 v-else :size="15" />
          {{ item.silent ? t("silent") : t("original") }}
        </span>
        <span class="inline-status">
          <Archive :size="15" />
          {{ item.compressed ? t("smaller") : t("standard") }}
        </span>
        <span class="row-actions">
          <button v-if="canOperate" class="icon-button ghost" :title="item.silent ? t('restoreAudio') : t('silentCopy')" :aria-label="item.silent ? t('restoreAudio') : t('silentCopy')" @click="toggleSilent(item)">
            <Volume2 v-if="item.silent" :size="18" />
            <VolumeX v-else :size="18" />
          </button>
          <button v-if="canOperate" class="icon-button ghost" :title="item.compressed ? t('standardCopy') : t('smallerCopy')" :aria-label="item.compressed ? t('standardCopy') : t('smallerCopy')" @click="toggleCompression(item)">
            <RotateCcw v-if="item.compressed" :size="18" />
            <Archive v-else :size="18" />
          </button>
          <button v-if="isAdmin" class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" @click="deleteMedia(item)">
            <Trash2 :size="18" />
          </button>
        </span>
      </div>
      <div v-if="!status.media.length" class="empty">{{ t("readyMedia") }}: 0</div>
    </div>
  </section>
</template>
