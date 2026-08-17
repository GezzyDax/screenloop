<script setup>
import { Archive, Columns3, Film, Search, Send, Upload, VolumeX } from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import MediaDialog from "../components/MediaDialog.vue";
import MediaWindowDialog from "../components/MediaWindowDialog.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";
import { formatShortDate } from "../utils/time";

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
  posterUrl,
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

// Which columns to draw. The name and the state always show -- one says what
// the clip is, the other whether it is on air, and a table without them is not
// a library. The rest is per-person and remembered here rather than on the
// server: it is a viewing preference, not a setting anybody administers.
const COLUMN_KEYS = ["zone", "window", "usage", "duration", "size"];
const COLUMN_STORAGE_KEY = "screenloop.media.columns";

function loadColumns() {
  const shown = Object.fromEntries(COLUMN_KEYS.map((key) => [key, true]));
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMN_STORAGE_KEY) || "{}");
    for (const key of COLUMN_KEYS) {
      if (typeof saved[key] === "boolean") shown[key] = saved[key];
    }
  } catch (_) {
    /* a corrupted preference is not worth a broken page */
  }
  return shown;
}

const columns = ref(loadColumns());
const columnsOpen = ref(false);

watch(
  columns,
  (value) => localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(value)),
  { deep: true },
);

const COLUMN_WIDTHS = { zone: ".9fr", window: ".85fr", usage: ".5fr", duration: ".45fr", size: ".55fr" };
const COLUMN_LABELS = {
  zone: "mediaZone",
  window: "mediaWindowColumn",
  usage: "mediaUsageColumn",
  duration: "duration",
  size: "size",
};

// The menu closes on any click outside it, the way a menu is expected to.
function closeColumns() {
  columnsOpen.value = false;
}
onMounted(() => document.addEventListener("click", closeColumns));
onBeforeUnmount(() => document.removeEventListener("click", closeColumns));

// The head and the rows have to agree, so both read one definition.
const gridStyle = computed(() => {
  const parts = ["28px", "1.8fr"];
  if (columns.value.zone) parts.push(COLUMN_WIDTHS.zone);
  if (columns.value.window) parts.push(COLUMN_WIDTHS.window);
  parts.push(".7fr"); // the state, which never hides
  for (const key of ["usage", "duration", "size"]) {
    if (columns.value[key]) parts.push(COLUMN_WIDTHS[key]);
  }
  return { gridTemplateColumns: parts.join(" ") };
});

// "1–30 сен", "с 1 окт", "до 30 сен". An empty window says nothing at all: most
// clips run until somebody takes them off, and printing "без срока" on every
// row would bury the handful that do have dates.
function windowLabel(item) {
  const from = formatShortDate(item.starts_at);
  const until = formatShortDate(item.expires_at);
  if (from && until) return `${from} — ${until}`;
  if (from) return `${t("mediaWindowFrom")} ${from}`;
  if (until) return `${t("mediaWindowUntil")} ${until}`;
  return "";
}

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
const selectedItems = computed(() => status.value.media.filter((item) => selected.value.has(item.id)));
const selectionAllSilent = computed(
  () => selectedItems.value.length > 0 && selectedItems.value.every((item) => !!item.silent),
);
const selectionAllCompressed = computed(
  () => selectedItems.value.length > 0 && selectedItems.value.every((item) => !!item.compressed),
);
const windowDialogOpen = ref(false);
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
        <option value="scheduled">{{ t("mediaState_scheduled") }}</option>
        <option value="published">{{ t("mediaState_published") }}</option>
        <option value="archived">{{ t("mediaState_archived") }}</option>
        <option value="expired">{{ t("mediaState_expired") }}</option>
        <option value="all">{{ t("mediaStateFilterAll") }}</option>
      </select>
      <span class="spacer"></span>
      <div class="column-picker" @click.stop>
        <button type="button" class="ghost" :aria-expanded="columnsOpen" @click="columnsOpen = !columnsOpen">
          <Columns3 :size="14" />
          <span>{{ t("mediaColumns") }}</span>
        </button>
        <div v-if="columnsOpen" class="column-menu">
          <label v-for="key in COLUMN_KEYS" :key="key" class="check-line">
            <input v-model="columns[key]" type="checkbox" />
            <span>{{ t(COLUMN_LABELS[key]) }}</span>
          </label>
        </div>
      </div>
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
      <button
        v-if="can('media.manage')"
        type="button"
        class="ghost"
        :disabled="isPending('media:bulk')"
        @click="windowDialogOpen = true"
      >
        {{ t("mediaWindowColumn") }}…
      </button>
      <!-- One button rather than a mute/unmute pair: it offers whichever of the
           two the selection is not already in, so the bar stays short. -->
      <button
        v-if="can('media.manage')"
        type="button"
        class="ghost"
        :disabled="isPending('media:bulk')"
        @click="bulkSetSilent(!selectionAllSilent)"
      >
        <VolumeX :size="14" />
        <span>{{ selectionAllSilent ? t("mediaBulkUnsilence") : t("mediaBulkSilence") }}</span>
      </button>
      <button
        v-if="can('media.manage')"
        type="button"
        class="ghost"
        :disabled="isPending('media:bulk')"
        @click="bulkSetCompressed(!selectionAllCompressed)"
      >
        <Archive :size="14" />
        <span>{{ selectionAllCompressed ? t("mediaBulkFullSize") : t("mediaBulkCompress") }}</span>
      </button>
      <button
        v-if="can('media.approve')"
        type="button"
        class="ghost"
        :disabled="isPending('media:bulk')"
        @click="bulkPublishMedia"
      >
        <Send :size="14" />
        <span>{{ t("mediaPublish") }}</span>
      </button>
      <button
        v-if="can('media.delete')"
        type="button"
        class="ghost"
        :disabled="isPending('media:bulk')"
        @click="bulkArchiveMedia"
      >
        <Archive :size="14" />
        <span>{{ t("mediaArchive") }}</span>
      </button>
      <button type="button" class="ghost" @click="clearMediaSelection">{{ t("cancel") }}</button>
    </div>

    <div class="table media-table">
      <div class="table-row head" :style="gridStyle">
        <span></span>
        <span>{{ t("name") }}</span>
        <span v-if="columns.zone">{{ t("mediaZone") }}</span>
        <span v-if="columns.window">{{ t("mediaWindowColumn") }}</span>
        <span>{{ t("mediaStateColumn") }}</span>
        <span v-if="columns.usage">{{ t("mediaUsageColumn") }}</span>
        <span v-if="columns.duration">{{ t("duration") }}</span>
        <span v-if="columns.size">{{ t("size") }}</span>
      </div>
      <div
        v-for="item in filteredMedia"
        :key="item.id"
        class="table-row media-row"
        :class="{ picked: selected.has(item.id) }"
        :style="gridStyle"
        @click="openMediaCard(item)"
      >
        <span class="select-cell" @click.stop>
          <input type="checkbox" :checked="selected.has(item.id)" @change="toggleMediaSelection(item.id)" />
        </span>
        <span class="media-name">
          <img v-if="item.has_poster" class="media-thumb" :src="posterUrl(item.id)" alt="" loading="lazy" />
          <span v-else class="media-thumb placeholder"><Film :size="14" /></span>
          <span class="media-name-text">
            <strong>{{ item.title }}</strong>
            <small>
              {{ item.original_name }}
              <template v-if="item.silent"> · {{ t("silent") }}</template>
              <template v-if="item.compressed"> · {{ t("smaller") }}</template>
            </small>
          </span>
        </span>
        <span v-if="columns.zone" class="muted">{{ zoneLabel(item.group_id) }}</span>
        <span v-if="columns.window" class="muted">{{ windowLabel(item) || "—" }}</span>
        <span class="state-cell">
          <b class="status-pill" :class="mediaStateClass(mediaState(item))">{{ t(`mediaState_${mediaState(item)}`) }}</b>
          <!-- Only when ffmpeg has something to say. A green "ready" on every
               row is noise that hides the one row that failed. -->
          <b v-if="item.status !== 'ready'" class="status-pill" :class="statusClass(item.status)">
            {{ tOr(`mediaStatus_${item.status}`, item.status) }}
          </b>
        </span>
        <span v-if="columns.usage" class="mono muted">{{ item.playlist_count || "—" }}</span>
        <span v-if="columns.duration" class="mono">{{ durationLabel(item.duration_seconds) }}</span>
        <span v-if="columns.size" class="mono">{{ formatBytes(item.size) }}</span>
      </div>
      <div v-if="!filteredMedia.length" class="empty">
        <Film :size="15" />
        <span>{{ can("media.upload") ? t("emptyMedia") : t("emptyMediaReadOnly") }}</span>
      </div>
    </div>
  </section>

  <MediaDialog />
  <MediaWindowDialog :open="windowDialogOpen" @close="windowDialogOpen = false" />
</template>
