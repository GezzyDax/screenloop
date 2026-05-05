<script setup>
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
      <h2>{{ t("mediaLibrary") }}</h2>
      <form v-if="canOperate" class="upload-form" @submit.prevent="uploadMedia">
        <input type="file" accept="video/*" @change="onUploadChange" />
        <button type="submit" :disabled="busy || !uploadFile">{{ busy ? t("uploading") : t("upload") }}</button>
      </form>
    </div>
    <div class="table media-table">
      <div class="table-row head"><span>{{ t("name") }}</span><span>{{ t("status") }}</span><span>{{ t("size") }}</span><span>{{ t("audio") }}</span><span>{{ t("compression") }}</span><span>{{ t("actions") }}</span></div>
      <div v-for="item in status.media" :key="item.id" class="table-row">
        <span><strong>{{ item.title }}</strong><small>{{ item.original_name }}</small></span>
        <span><b :class="statusClass(item.status)">{{ item.status }}</b></span>
        <span class="mono">{{ formatBytes(item.size) }}</span>
        <span>{{ item.silent ? t("silent") : t("original") }}</span>
        <span>{{ item.compressed ? t("smaller") : t("standard") }}</span>
        <span class="row-actions">
          <button v-if="canOperate" class="ghost" @click="toggleSilent(item)">{{ item.silent ? t("restoreAudio") : t("silentCopy") }}</button>
          <button v-if="canOperate" class="ghost" @click="toggleCompression(item)">{{ item.compressed ? t("standardCopy") : t("smallerCopy") }}</button>
          <button v-if="isAdmin" class="danger" @click="deleteMedia(item)">{{ t("delete") }}</button>
        </span>
      </div>
    </div>
  </section>
</template>
