<script setup>
import { ChevronDown, ChevronRight, Download, Edit3, Folder, FolderOpen, FolderTree, Layers, Plus, RefreshCcw, Search, Trash2, Upload } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import TvCard from "../components/TvCard.vue";
import GroupEditDialog from "../components/GroupEditDialog.vue";
import TvCreateDialog from "../components/TvCreateDialog.vue";
import TvDetailsPanel from "../components/TvDetailsPanel.vue";
import TvEditDialog from "../components/TvEditDialog.vue";
import { shortUrl } from "../composables/tvCard";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  addScannedTv,
  beginEditTv,
  cancelEditTv,
  createGroup,
  createTv,
  deleteGroup,
  deleteTv,
  detectTv,
  exportTvs,
  groupForm,
  groups,
  importTvsFile,
  isAdmin,
  isPending,
  loadGroups,
  loadNodes,
  moveGroup,
  nodes,
  startGroupCreate,
  startGroupEdit,
  startTvCreate,
  saveTv,
  scanDevices,
  scanTvs,
  selectTv,
  statusClass,
  selectedGroupId,
  status,
  toggleTvAutoplay,
  tvEditForms,
  tvForm,
  tvProfiles,
  visibleTvs,
} = useScreenloop();

// The tree shows groups and the screens inside them, collapsed by default so a
// large estate does not arrive as one long list. Expansion lives here rather
// than in the store because it is view state -- and because it must survive the
// status poll that replaces `status.tvs` every few seconds.
const expandedGroups = ref(new Set());

function toggleGroup(id) {
  const next = new Set(expandedGroups.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedGroups.value = next;
}

const childGroups = computed(() => {
  const map = new Map();
  for (const group of groups.value) {
    const key = group.parent_id || 0;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(group);
  }
  return map;
});

const tvsByGroup = computed(() => {
  const map = new Map();
  for (const tv of status.value.tvs) {
    const key = tv.group_id || 0;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(tv);
  }
  return map;
});

// The backend counts only screens attached directly to a group, but selecting a
// branch filters to its whole subtree, so a parent showing 0 next to a filter
// that yields three is just wrong. Rolled up here.
const subtreeCounts = computed(() => {
  const totals = new Map();
  const visit = (groupId) => {
    let total = (tvsByGroup.value.get(groupId) || []).length;
    for (const child of childGroups.value.get(groupId) || []) total += visit(child.id);
    totals.set(groupId, total);
    return total;
  };
  for (const root of childGroups.value.get(0) || []) visit(root.id);
  return totals;
});

function branchSize(groupId) {
  return (childGroups.value.get(groupId)?.length || 0) + (tvsByGroup.value.get(groupId)?.length || 0);
}

const treeRows = computed(() => {
  const rows = [];
  const walk = (parentId, depth) => {
    for (const group of childGroups.value.get(parentId) || []) {
      rows.push({ key: `g${group.id}`, kind: "group", group, depth });
      if (expandedGroups.value.has(group.id)) {
        walk(group.id, depth + 1);
        for (const tv of tvsByGroup.value.get(group.id) || []) {
          rows.push({ key: `t${tv.id}`, kind: "tv", tv, depth: depth + 1 });
        }
      }
    }
  };
  walk(0, 0);
  return rows;
});

const ungroupedTvs = computed(() => tvsByGroup.value.get(0) || []);

onMounted(() => {
  loadGroups().catch(() => {});
  if (isAdmin.value) loadNodes().catch(() => {});
});

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
          <button class="action-button" @click="startTvCreate">
          <Plus :size="14" />
          <span>{{ t("addTv") }}</span>
        </button>
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

    <div class="tvs-layout">
      <aside class="panel groups-aside">
        <div class="section-title">
          <FolderTree :size="15" />
          <div>
            <h2>{{ t("groups") }}</h2>
            <p class="muted">{{ t("groupsAsideHint") }}</p>
          </div>
        </div>

        <div class="group-tree">
          <div class="group-row" :class="{ active: selectedGroupId === '' }">
            <button type="button" class="group-row-name" @click="selectedGroupId = ''">
              <Layers :size="13" />{{ t("allGroups") }}
            </button>
            <span class="group-row-count">{{ status.tvs.length }}</span>
            <span class="group-row-actions"></span>
          </div>

          <template v-for="row in treeRows" :key="row.key">
            <div
              v-if="row.kind === 'group'"
              class="group-row"
              :class="{ active: selectedGroupId === row.group.id }"
              :title="row.group.path"
            >
              <span class="group-row-lead" :style="{ paddingLeft: `${row.depth * 12}px` }">
                <button
                  v-if="branchSize(row.group.id)"
                  type="button"
                  class="tree-toggle"
                  :aria-label="expandedGroups.has(row.group.id) ? t('collapse') : t('expand')"
                  @click="toggleGroup(row.group.id)"
                >
                  <ChevronDown v-if="expandedGroups.has(row.group.id)" :size="12" />
                  <ChevronRight v-else :size="12" />
                </button>
                <span v-else class="tree-toggle placeholder"></span>
                <button type="button" class="group-row-name" @click="selectedGroupId = row.group.id">
                  <Folder :size="13" />{{ row.group.name }}
                </button>
              </span>
              <span class="group-row-count">{{ subtreeCounts.get(row.group.id) ?? 0 }}</span>
              <span class="group-row-actions">
                <button
                  v-if="isAdmin"
                  class="icon-button ghost"
                  :title="t('edit')"
                  :aria-label="t('edit')"
                  :disabled="isPending(`group:${row.group.id}`)"
                  @click="startGroupEdit(row.group)"
                >
                  <Edit3 :size="13" />
                </button>
              </span>
            </div>

            <div v-else class="group-row tv-row" :title="`${row.tv.name} · ${row.tv.ip}`">
              <span class="group-row-lead" :style="{ paddingLeft: `${row.depth * 12 + 18}px` }">
                <button type="button" class="group-row-name" @click="selectTv(row.tv)">
                  <span class="tv-dot" :class="statusClass(!!row.tv.online)"></span>{{ row.tv.name }}
                </button>
              </span>
              <span class="group-row-count"></span>
              <span class="group-row-actions">
                <button
                  v-if="isAdmin"
                  class="icon-button ghost"
                  :title="t('edit')"
                  :aria-label="t('edit')"
                  @click="beginEditTv(row.tv)"
                >
                  <Edit3 :size="13" />
                </button>
              </span>
            </div>
          </template>

          <div class="group-row" :class="{ active: selectedGroupId === 'none' }">
            <span class="group-row-lead">
              <button
                v-if="ungroupedTvs.length"
                type="button"
                class="tree-toggle"
                :aria-label="expandedGroups.has(0) ? t('collapse') : t('expand')"
                @click="toggleGroup(0)"
              >
                <ChevronDown v-if="expandedGroups.has(0)" :size="12" />
                <ChevronRight v-else :size="12" />
              </button>
              <span v-else class="tree-toggle placeholder"></span>
              <button type="button" class="group-row-name" @click="selectedGroupId = 'none'">
                <FolderOpen :size="13" />{{ t("withoutGroup") }}
              </button>
            </span>
            <span class="group-row-count">{{ ungroupedCount }}</span>
            <span class="group-row-actions"></span>
          </div>

          <div v-if="expandedGroups.has(0)" v-for="tv in ungroupedTvs" :key="`u${tv.id}`" class="group-row tv-row">
            <span class="group-row-lead" style="padding-left: 18px">
              <button type="button" class="group-row-name" @click="selectTv(tv)">
                <span class="tv-dot" :class="statusClass(!!tv.online)"></span>{{ tv.name }}
              </button>
            </span>
            <span class="group-row-count"></span>
            <span class="group-row-actions"></span>
          </div>
        </div>

        <button v-if="isAdmin" type="button" class="ghost action-button group-add" @click="startGroupCreate">
          <Plus :size="13" />
          <span>{{ t("addGroup") }}</span>
        </button>
      </aside>

      <div class="tvs-column">
    <div class="tv-admin-grid">
        <TvCard v-for="tv in visibleTvs" :key="tv.id" :tv="tv" variant="admin">
          <template #footer>
            <div v-if="isAdmin" class="tv-config-strip">
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
              <div class="row-actions">
                <button class="icon-button ghost" :title="t('edit')" :aria-label="t('edit')" @click="beginEditTv(tv)">
                  <Edit3 :size="15" />
                </button>
                <button class="icon-button ghost" :title="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :aria-label="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :disabled="isPending(`tv:${tv.id}`)" @click="toggleTvAutoplay(tv)">
                  <RefreshCcw :size="15" />
                </button>
                <button class="icon-button ghost" :title="t('detect')" :aria-label="t('detect')" :disabled="isPending(`tv:${tv.id}`)" @click="detectTv(tv)">
                  <Search :size="15" />
                </button>
                <span class="spacer"></span>
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
      </div>
    </div>

    <TvEditDialog />
  <GroupEditDialog />
  <TvCreateDialog />
  <TvDetailsPanel />
</section>
</template>

<style scoped>

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

</style>
