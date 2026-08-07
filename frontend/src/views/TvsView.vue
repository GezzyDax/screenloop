<script setup>
import { Download, Edit3, Plus, RefreshCcw, Search, Trash2, Upload } from "@lucide/vue";
import { computed, onMounted } from "vue";
import TvCard from "../components/TvCard.vue";
import { shortUrl } from "../composables/tvCard";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  addScannedTv,
  beginEditTv,
  cancelEditTv,
  can,
  createGroup,
  createTv,
  deleteGroup,
  deleteTv,
  detectTv,
  exportTvs,
  groupForm,
  groupScheduleForms,
  groups,
  importTvsFile,
  isAdmin,
  isPending,
  loadGroups,
  loadNodes,
  moveGroup,
  nodes,
  renameGroup,
  saveTv,
  saveGroupSchedule,
  scanDevices,
  scanTvs,
  selectedGroupId,
  status,
  toggleTvAutoplay,
  tvEditForms,
  tvForm,
  tvProfiles,
  visibleTvs,
} = useScreenloop();

onMounted(() => {
  loadGroups().catch(() => {});
  if (isAdmin.value) loadNodes().catch(() => {});
});

function promptRename(group) {
  const name = window.prompt(t("groupName"), group.name);
  if (name !== null) renameGroup(group, name);
}

// `status` is a ref, and <script setup> only unwraps refs inside the template.
// Reading `status.tvs` here gave undefined and threw during render, which took
// the whole page down rather than just this counter.
const ungroupedCount = computed(() => status.value.tvs.filter((tv) => !tv.group_id).length);
const canManageGroups = computed(() => can("group.manage"));
</script>

<template>
  <section class="stack">
    <div v-if="isAdmin" class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("tvManagement") }}</h2>
          <p class="muted">{{ t("configuredTvs") }}</p>
        </div>
        <div class="top-actions">
          <button class="ghost action-button" :disabled="isPending('tv:scan')" @click="scanTvs">
            <Search :size="14" />
            <span>{{ t("scanNetwork") }}</span>
          </button>
          <button class="ghost action-button" @click="exportTvs">
            <Download :size="14" />
            <span>{{ t("exportTvConfigs") }}</span>
          </button>
          <label class="file-button ghost">
            <Upload :size="14" />
            <span>{{ t("importTvConfigs") }}</span>
            <input type="file" accept="application/json,.json" @change="importTvsFile" />
          </label>
        </div>
      </div>

      <form class="form-grid tv-create-form" @submit.prevent="createTv">
        <label>{{ t("name") }}<input v-model="tvForm.name" :placeholder="t('tvNamePlaceholder')" required /></label>
        <label>{{ t("ip") }}
          <input
            v-model="tvForm.ip"
            placeholder="192.168.1.50"
            required
            pattern="^\d{1,3}(\.\d{1,3}){3}$"
            :title="t('ipFormatHint')"
          />
        </label>
        <label>{{ t("profile") }}
          <select v-model="tvForm.profile">
            <option v-for="(profile, key) in tvProfiles" :key="key" :value="key">{{ profile.name || key }}{{ profile.source === "custom" ? ` · ${t("templateCustom")}` : "" }}</option>
          </select>
        </label>
        <label>{{ t("node") }}
          <select v-model="tvForm.node_id">
            <option value="">{{ t("localNode") }}</option>
            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
          </select>
        </label>
        <label>{{ t("group") }}
          <select v-model="tvForm.group_id">
            <option value="">{{ t("withoutGroup") }}</option>
            <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.path }}</option>
          </select>
        </label>
        <button type="submit" class="action-button" :disabled="isPending('tv:create')">
          <Plus :size="14" />
          <span>{{ t("addTv") }}</span>
        </button>
      </form>

      <div v-if="scanDevices.length" class="list scan-list">
        <article v-for="device in scanDevices" :key="`${device.ip}-${device.control_url || device.location}`" class="list-item scan-device">
          <span>
            <strong>{{ device.friendly_name || device.ip }}</strong>
            <small>{{ device.ip }} · {{ device.profile || "generic_dlna" }} · {{ device.manufacturer || t("unknown") }} · {{ device.model_name || t("unknown") }}</small>
            <small class="mono">{{ device.control_url || device.location || "-" }}</small>
          </span>
          <button v-if="!device.configured" class="action-button" :disabled="isPending(`tv:add:${device.ip}`)" @click="addScannedTv(device)">
            <Plus :size="14" />
            <span>{{ t("addTv") }}</span>
          </button>
          <span v-else class="pill ok">{{ t("configured") }}</span>
        </article>
      </div>
    </div>

    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("groups") }}</h2>
          <p class="muted">{{ t("groupsHint") }}</p>
        </div>
      </div>

      <div class="group-filter">
        <button class="chip" :class="{ active: selectedGroupId === '' }" @click="selectedGroupId = ''">
          {{ t("allGroups") }} · {{ status.tvs.length }}
        </button>
        <button
          v-for="group in groups"
          :key="group.id"
          class="chip"
          :class="{ active: selectedGroupId === group.id }"
          :style="{ marginLeft: `${group.depth * 14}px` }"
          :title="group.path"
          @click="selectedGroupId = group.id"
        >
          {{ group.name }} · {{ group.tv_count }}
        </button>
        <button class="chip" :class="{ active: selectedGroupId === 'none' }" @click="selectedGroupId = 'none'">
          {{ t("withoutGroup") }} · {{ ungroupedCount }}
        </button>
      </div>

      <form v-if="canManageGroups" class="inline-form group-create" @submit.prevent="createGroup">
        <input v-model="groupForm.name" :placeholder="t('groupNamePlaceholder')" required />
        <select v-model="groupForm.parent_id">
          <option value="">{{ t("groupRoot") }}</option>
          <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.path }}</option>
        </select>
        <button type="submit" class="action-button" :disabled="isPending('group:create')">
          <Plus :size="14" />
          <span>{{ t("addGroup") }}</span>
        </button>
      </form>

      <div v-if="canManageGroups && groups.length" class="table groups-table">
        <div class="table-row head">
          <span>{{ t("groupName") }}</span>
          <span>{{ t("groupParent") }}</span>
          <span :title="t('groupScheduleHint')">{{ t("groupSchedule") }}</span>
          <span>{{ t("tvs") }}</span>
          <span>{{ t("actions") }}</span>
        </div>
        <div v-for="group in groups" :key="group.id" class="table-row">
          <span :style="{ paddingLeft: `${group.depth * 16}px` }"><strong>{{ group.name }}</strong></span>
          <span>
            <select :value="group.parent_id || ''" @change="moveGroup(group, $event.target.value)">
              <option value="">{{ t("groupRoot") }}</option>
              <option v-for="candidate in groups" :key="candidate.id" :value="candidate.id" :disabled="candidate.id === group.id">
                {{ candidate.path }}
              </option>
            </select>
          </span>
          <span v-if="groupScheduleForms[group.id]" class="group-schedule-cell">
            <select v-model="groupScheduleForms[group.id].schedule_mode" :aria-label="t('groupSchedule')">
              <option value="inherit">{{ t("groupScheduleInherit") }}</option>
              <option value="always">{{ t("scheduleModeAlways") }}</option>
              <option value="custom">{{ t("scheduleModeCustom") }}</option>
            </select>
            <span v-if="groupScheduleForms[group.id].schedule_mode === 'custom'" class="group-schedule-window">
              <input v-model="groupScheduleForms[group.id].schedule_days" :aria-label="t('scheduleDays')" placeholder="0,1,2,3,4" />
              <input v-model="groupScheduleForms[group.id].schedule_start" :aria-label="t('scheduleStart')" type="time" />
              <input v-model="groupScheduleForms[group.id].schedule_end" :aria-label="t('scheduleEnd')" type="time" />
            </span>
            <small v-else-if="groupScheduleForms[group.id].schedule_mode === 'inherit'" class="muted">{{ t("groupScheduleHint") }}</small>
            <button class="ghost" :disabled="isPending(`group:${group.id}:schedule`)" @click="saveGroupSchedule(group)">
              {{ t("save") }}
            </button>
          </span>
          <span>{{ group.tv_count }}</span>
          <span class="row-actions">
            <button class="icon-button ghost" :title="t('rename')" :aria-label="t('rename')" @click="promptRename(group)">
              <Edit3 :size="15" />
            </button>
            <button class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" :disabled="isPending(`group:${group.id}`)" @click="deleteGroup(group)">
              <Trash2 :size="15" />
            </button>
          </span>
        </div>
      </div>
    </div>

    <div class="tv-admin-grid">
      <TvCard v-for="tv in visibleTvs" :key="tv.id" :tv="tv" variant="admin">
        <template #footer>
          <form v-if="isAdmin && tvEditForms[tv.id]" class="tv-edit-form" @submit.prevent="saveTv(tv)">
            <label>{{ t("name") }}<input v-model="tvEditForms[tv.id].name" required /></label>
            <label>{{ t("ip") }}
              <input v-model="tvEditForms[tv.id].ip" required pattern="^\d{1,3}(\.\d{1,3}){3}$" :title="t('ipFormatHint')" />
            </label>
            <label>{{ t("profile") }}
              <select v-model="tvEditForms[tv.id].profile">
                <option v-for="(profile, key) in tvProfiles" :key="key" :value="key">{{ profile.name || key }}{{ profile.source === "custom" ? ` · ${t("templateCustom")}` : "" }}</option>
              </select>
            </label>
            <label>{{ t("playlist") }}
              <select v-model="tvEditForms[tv.id].playlist_id">
                <option value="">{{ t("noPlaylist") }}</option>
                <option v-for="playlist in status.playlists" :key="playlist.id" :value="playlist.id">{{ playlist.name }}</option>
              </select>
            </label>
            <label>{{ t("node") }}
              <select v-model="tvEditForms[tv.id].node_id">
                <option value="">{{ t("localNode") }}</option>
                <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
              </select>
            </label>
            <label>{{ t("group") }}
              <select v-model="tvEditForms[tv.id].group_id">
                <option value="">{{ t("withoutGroup") }}</option>
                <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.path }}</option>
              </select>
            </label>
            <label class="check-label"><input v-model="tvEditForms[tv.id].autoplay" type="checkbox" /> {{ t("autoplay") }}</label>
            <label class="wide">{{ t("controlUrl") }}<input v-model="tvEditForms[tv.id].control_url" placeholder="http://TV-IP:7676/smp_24_" /></label>
            <label>{{ t("scheduleMode") }}
              <select v-model="tvEditForms[tv.id].schedule_mode">
                <option value="inherit">{{ t("scheduleModeInherit") }}</option>
                <option value="always">{{ t("scheduleModeAlways") }}</option>
                <option value="custom">{{ t("scheduleModeCustom") }}</option>
              </select>
            </label>
            <template v-if="tvEditForms[tv.id].schedule_mode === 'custom'">
              <label>{{ t("scheduleDays") }}<input v-model="tvEditForms[tv.id].schedule_days" placeholder="0,1,2,3,4" /></label>
              <label>{{ t("scheduleStart") }}<input v-model="tvEditForms[tv.id].schedule_start" type="time" /></label>
              <label>{{ t("scheduleEnd") }}<input v-model="tvEditForms[tv.id].schedule_end" type="time" /></label>
            </template>
            <div class="row-actions wide">
              <button type="submit" :disabled="isPending(`tv:${tv.id}`)">{{ t("save") }}</button>
              <button type="button" class="ghost" @click="cancelEditTv(tv)">{{ t("cancel") }}</button>
              <button type="button" class="danger" :disabled="isPending(`tv:${tv.id}`)" @click="deleteTv(tv)">{{ t("delete") }}</button>
            </div>
          </form>

          <div v-else-if="isAdmin" class="tv-config-strip">
            <div>
              <span>{{ t("autoplay") }}</span>
              <strong>{{ tv.autoplay ? t("enabled") : t("disabled") }}</strong>
            </div>
            <div>
              <span>{{ t("controlUrl") }}</span>
              <strong class="mono" :title="tv.control_url || ''">{{ shortUrl(tv.control_url) }}</strong>
            </div>
            <div>
              <span>{{ t("renderingControlUrl") }}</span>
              <strong class="mono" :title="tv.rendering_control_url || ''">{{ shortUrl(tv.rendering_control_url) }}</strong>
            </div>
            <div class="row-actions wide">
              <button class="icon-button ghost" :title="t('edit')" :aria-label="t('edit')" @click="beginEditTv(tv)">
                <Edit3 :size="15" />
              </button>
              <button class="icon-button ghost" :title="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :aria-label="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :disabled="isPending(`tv:${tv.id}`)" @click="toggleTvAutoplay(tv)">
                <RefreshCcw :size="15" />
              </button>
              <button class="icon-button ghost" :title="t('detect')" :aria-label="t('detect')" :disabled="isPending(`tv:${tv.id}`)" @click="detectTv(tv)">
                <Search :size="15" />
              </button>
              <button class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" :disabled="isPending(`tv:${tv.id}`)" @click="deleteTv(tv)">
                <Trash2 :size="15" />
              </button>
            </div>
          </div>
        </template>
      </TvCard>
      <div v-if="!visibleTvs.length" class="empty">
        {{ status.tvs.length ? t("noTvsInGroup") : t("noTvs") }}
      </div>
    </div>
  </section>
</template>

<style scoped>
.group-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.chip {
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
}

.chip.active {
  font-weight: 700;
}

.group-create {
  margin-bottom: 14px;
}

.groups-table .table-row {
  grid-template-columns: minmax(120px, 1.3fr) minmax(140px, 1.3fr) minmax(220px, 2fr) 0.4fr auto;
}

@media (max-width: 900px) {
  .groups-table .table-row {
    grid-template-columns: 1fr;
  }
}
</style>
