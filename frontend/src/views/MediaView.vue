<script setup>
import { Film, Search, Upload } from "@lucide/vue";
import { computed, ref } from "vue";
import MediaDialog from "../components/MediaDialog.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";

const { t, tOr } = useI18n();
const {
  bulkArchiveMedia,
  bulkMoveMedia,
  busy,
  can,
  clearMediaSelection,
  groups,
  isPending,
  mediaSelection,
  mediaState,
  mediaStateClass,
  mediaStateFilter,
  mediaZoneFilter,
  onUploadChange,
  openMediaCard,
  status,
  statusClass,
  toggleMediaSelection,
  uploadFile,
  uploadGroup,
  uploadMedia,
  uploadProgress,
} = useScreenloop();

const query = ref("");
const bulkTarget = ref("");

// Which zone a clip belongs to decides who else can see it, so it stays on the
// row rather than hiding behind the card.
function zoneLabel(groupId) {
  if (!groupId) return t("mediaZoneShared");
  // A clip that belongs to a zone is never "shared", so a name we cannot
  // resolve -- somebody who may approve clips but not read the group tree --
  // shows as unknown rather than borrowing the label for company-wide.
  return groups.value.find((group) => group.id === groupId)?.path || "—";
}

function durationLabel(seconds) {
  if (!seconds) return "—";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

const filteredMedia = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const zone = mediaZoneFilter.value;
  const state = mediaStateFilter.value;
  return status.value.media.filter((item) => {
    // "active" is the default view: an archived clip is still there, behind
    // the filter, rather than gone.
    const itemState = mediaState(item);
    if (state === "active" && ["archived", "expired"].includes(itemState)) return false;
    if (!["active", "all"].includes(state) && itemState !== state) return false;
    if (zone === "shared" && item.group_id) return false;
    if (zone && zone !== "shared" && String(item.group_id || "") !== zone) return false;
    if (!needle) return true;
    return (
      item.title.toLowerCase().includes(needle) ||
      (item.original_name || "").toLowerCase().includes(needle) ||
      (item.description || "").toLowerCase().includes(needle)
    );
  });
});

const selected = computed(() => new Set(mediaSelection.value));
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <div>
        <h2>{{ t("mediaLibrary") }}</h2>
        <p class="muted">{{ t("readyMedia") }}: {{ status.media.filter((item) => item.status === "ready").length }}</p>
      </div>
      <form v-if="can('media.upload')" class="upload-form toolbar" @submit.prevent="uploadMedia">
        <select v-model="uploadGroup" class="upload-zone" :aria-label="t('uploadZone')" :title="t('uploadZoneHint')">
          <option value="">{{ t("uploadZoneAuto") }}</option>
          <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.path }}</option>
        </select>
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

    <div class="library-filters">
      <label class="search-field">
        <Search :size="14" />
        <input v-model="query" type="search" :placeholder="t('searchPlaceholder')" :aria-label="t('searchPlaceholder')" />
      </label>
      <select v-model="mediaZoneFilter" :aria-label="t('filterZone')">
        <option value="">{{ t("allZones") }}</option>
        <option value="shared">{{ t("mediaZoneShared") }}</option>
        <option v-for="group in groups" :key="group.id" :value="String(group.id)">{{ group.path }}</option>
      </select>
      <select v-model="mediaStateFilter" :aria-label="t('mediaStateColumn')">
        <option value="active">{{ t("mediaStateFilterActive") }}</option>
        <option value="draft">{{ t("mediaState_draft") }}</option>
        <option value="published">{{ t("mediaState_published") }}</option>
        <option value="archived">{{ t("mediaState_archived") }}</option>
        <option value="expired">{{ t("mediaState_expired") }}</option>
        <option value="all">{{ t("mediaStateFilterAll") }}</option>
      </select>
    </div>

    <!-- The bulk bar only exists while something is selected: an idle toolbar of
         destructive actions is exactly what this page had too much of. -->
    <div v-if="mediaSelection.length" class="bulk-bar">
      <span>{{ t("mediaSelected", { count: mediaSelection.length }) }}</span>
      <span class="spacer"></span>
      <select v-model="bulkTarget" :aria-label="t('mediaMoveTo')">
        <option value="">{{ t("mediaMoveTo") }}…</option>
        <option value="shared">{{ t("mediaZoneShared") }}</option>
        <option v-for="group in groups" :key="group.id" :value="String(group.id)">{{ group.path }}</option>
      </select>
      <button
        type="button"
        class="ghost"
        :disabled="!bulkTarget || isPending('media:bulk')"
        @click="bulkMoveMedia(bulkTarget === 'shared' ? '' : bulkTarget)"
      >
        {{ t("move") }}
      </button>
      <button type="button" class="ghost" :disabled="isPending('media:bulk')" @click="bulkArchiveMedia">
        {{ t("mediaArchive") }}
      </button>
      <button type="button" class="ghost" @click="clearMediaSelection">{{ t("cancel") }}</button>
    </div>

    <div class="table media-table">
      <div class="table-row head">
        <span></span>
        <span>{{ t("name") }}</span>
        <span>{{ t("mediaZone") }}</span>
        <span>{{ t("mediaStateColumn") }}</span>
        <span>{{ t("status") }}</span>
        <span>{{ t("duration") }}</span>
        <span>{{ t("size") }}</span>
      </div>
      <div
        v-for="item in filteredMedia"
        :key="item.id"
        class="table-row media-row"
        :class="{ picked: selected.has(item.id) }"
        @click="openMediaCard(item)"
      >
        <span class="select-cell" @click.stop>
          <input type="checkbox" :checked="selected.has(item.id)" @change="toggleMediaSelection(item.id)" />
        </span>
        <span class="media-name">
          <strong>{{ item.title }}</strong>
          <small>
            {{ item.original_name }}
            <template v-if="item.silent"> · {{ t("silent") }}</template>
            <template v-if="item.compressed"> · {{ t("smaller") }}</template>
          </small>
        </span>
        <span class="muted">{{ zoneLabel(item.group_id) }}</span>
        <span><b class="status-pill" :class="mediaStateClass(mediaState(item))">{{ t(`mediaState_${mediaState(item)}`) }}</b></span>
        <span><b class="status-pill" :class="statusClass(item.status)">{{ tOr(`mediaStatus_${item.status}`, item.status) }}</b></span>
        <span class="mono">{{ durationLabel(item.duration_seconds) }}</span>
        <span class="mono">{{ formatBytes(item.size) }}</span>
      </div>
      <div v-if="!filteredMedia.length" class="empty">
        <Film :size="15" />
        <span>{{ t("emptyMedia") }}</span>
      </div>
    </div>
  </section>

  <MediaDialog />
</template>
