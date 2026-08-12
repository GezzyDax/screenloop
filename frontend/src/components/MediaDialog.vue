<script setup>
// The clip card. Before this, a clip could only be muted, compressed or
// deleted from the row — its name was the uploaded filename and could never be
// changed, and nothing told the operator where the clip was actually used.
// Everything about one clip now lives in one dialog.
import { Archive, Film, Trash2, Tv, VolumeX } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";

const { t, tOr } = useI18n();
const {
  closeMediaCard,
  deleteMedia,
  editingMedia,
  groups,
  isPending,
  mayEdit,
  mediaForm,
  mediaUsage,
  saveMediaCard,
  statusClass,
} = useScreenloop();

const item = computed(() => editingMedia.value);
const busy = computed(() => (item.value ? isPending(`media:${item.value.id}`) : false));
const editable = computed(() => (item.value ? mayEdit(item.value, "media.manage") : false));
const removable = computed(() => (item.value ? mayEdit(item.value, "media.delete") : false));

const duration = computed(() => {
  const seconds = item.value?.duration_seconds;
  if (!seconds) return "—";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
});

async function remove() {
  const current = item.value;
  if (!current) return;
  closeMediaCard();
  await deleteMedia(current);
}
</script>

<template>
  <div v-if="item" class="modal-backdrop" @click.self="closeMediaCard">
    <div class="modal modal-wide media-card" role="dialog" aria-modal="true">
      <header class="media-card-head">
        <div class="section-title">
          <Film :size="15" />
          <div>
            <h3>{{ t("mediaCard") }}</h3>
            <p class="muted">{{ item.original_name }}</p>
          </div>
        </div>
        <b class="status-pill" :class="statusClass(item.status)">
          {{ tOr(`mediaStatus_${item.status}`, item.status) }}
        </b>
      </header>

      <form class="media-card-body" @submit.prevent="saveMediaCard">
        <fieldset>
          <legend>{{ t("mediaProperties") }}</legend>
          <label class="wide">{{ t("name") }}
            <input v-model="mediaForm.title" :disabled="!editable" required maxlength="160" />
          </label>
          <label class="wide">{{ t("mediaDescription") }}
            <textarea
              v-model="mediaForm.description"
              :disabled="!editable"
              rows="2"
              maxlength="1000"
              :placeholder="t('mediaDescriptionHint')"
            ></textarea>
          </label>

          <div class="field-grid">
            <label>{{ t("mediaZone") }}
              <select v-model="mediaForm.group_id" :disabled="!editable">
                <option value="">{{ t("mediaZoneShared") }}</option>
                <option v-for="group in groups" :key="group.id" :value="String(group.id)">{{ group.path }}</option>
              </select>
              <small class="muted">{{ t("mediaZoneHint") }}</small>
            </label>
          </div>

          <div class="toggle-row">
            <!-- The label says what the box does, not what the clip is now:
                 a checkbox already carries the state. -->
            <label class="check-line">
              <input v-model="mediaForm.silent" type="checkbox" :disabled="!editable" />
              <VolumeX :size="13" />
              <span>{{ t("mediaSilentLabel") }}</span>
            </label>
            <label class="check-line">
              <input v-model="mediaForm.compressed" type="checkbox" :disabled="!editable" />
              <Archive :size="13" />
              <span>{{ t("mediaCompressedLabel") }}</span>
            </label>
          </div>

          <dl class="facts">
            <div><dt>{{ t("size") }}</dt><dd class="mono">{{ formatBytes(item.size) }}</dd></div>
            <div><dt>{{ t("duration") }}</dt><dd class="mono">{{ duration }}</dd></div>
          </dl>
        </fieldset>

        <fieldset>
          <legend>{{ t("mediaUsage") }}</legend>
          <p v-if="!mediaUsage" class="muted">…</p>
          <template v-else>
            <ul v-if="mediaUsage.playlists.length" class="usage-list">
              <li v-for="playlist in mediaUsage.playlists" :key="playlist.id">{{ playlist.name }}</li>
            </ul>
            <p v-else class="muted">{{ t("mediaUsageNone") }}</p>
            <div v-if="mediaUsage.tvs.length" class="usage-now">
              <Tv :size="13" />
              <span>{{ t("mediaPlayingNow") }}: {{ mediaUsage.tvs.map((tv) => tv.name).join(", ") }}</span>
            </div>
          </template>
        </fieldset>

        <footer class="tv-edit-actions">
          <button v-if="removable" type="button" class="icon-button danger" :title="t('delete')" :disabled="busy" @click="remove">
            <Trash2 :size="14" />
          </button>
          <span class="spacer"></span>
          <button type="button" class="ghost" @click="closeMediaCard">{{ t("cancel") }}</button>
          <button v-if="editable" type="submit" :disabled="busy">{{ t("save") }}</button>
        </footer>
      </form>
    </div>
  </div>
</template>
