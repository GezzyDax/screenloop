<script setup>
import { Download, Edit3, Plus, RefreshCcw, Search, Trash2, Upload } from "@lucide/vue";
import { onMounted } from "vue";
import TvCard from "../components/TvCard.vue";
import { shortUrl } from "../composables/tvCard";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  addScannedTv,
  beginEditTv,
  cancelEditTv,
  createTv,
  deleteTv,
  detectTv,
  exportTvs,
  importTvsFile,
  isAdmin,
  isPending,
  loadNodes,
  nodes,
  saveTv,
  scanDevices,
  scanTvs,
  status,
  toggleTvAutoplay,
  tvEditForms,
  tvForm,
  tvProfiles,
} = useScreenloop();

onMounted(() => {
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
          <button class="ghost action-button" :disabled="isPending('tv:scan')" @click="scanTvs">
            <Search :size="17" />
            <span>{{ t("scanNetwork") }}</span>
          </button>
          <button class="ghost action-button" @click="exportTvs">
            <Download :size="17" />
            <span>{{ t("exportTvConfigs") }}</span>
          </button>
          <label class="file-button ghost">
            <Upload :size="17" />
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
            <option v-for="(_, key) in tvProfiles" :key="key" :value="key">{{ key }}</option>
          </select>
        </label>
        <label>{{ t("node") }}
          <select v-model="tvForm.node_id">
            <option value="">{{ t("localNode") }}</option>
            <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
          </select>
        </label>
        <button type="submit" class="action-button" :disabled="isPending('tv:create')">
          <Plus :size="17" />
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
            <Plus :size="17" />
            <span>{{ t("addTv") }}</span>
          </button>
          <span v-else class="pill ok">{{ t("configured") }}</span>
        </article>
      </div>
    </div>

    <div class="tv-admin-grid">
      <TvCard v-for="tv in status.tvs" :key="tv.id" :tv="tv" variant="admin">
        <template #footer>
          <form v-if="isAdmin && tvEditForms[tv.id]" class="tv-edit-form" @submit.prevent="saveTv(tv)">
            <label>{{ t("name") }}<input v-model="tvEditForms[tv.id].name" required /></label>
            <label>{{ t("ip") }}
              <input v-model="tvEditForms[tv.id].ip" required pattern="^\d{1,3}(\.\d{1,3}){3}$" :title="t('ipFormatHint')" />
            </label>
            <label>{{ t("profile") }}
              <select v-model="tvEditForms[tv.id].profile">
                <option v-for="(_, key) in tvProfiles" :key="key" :value="key">{{ key }}</option>
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
            <label class="check-label"><input v-model="tvEditForms[tv.id].autoplay" type="checkbox" /> {{ t("autoplay") }}</label>
            <label class="wide">{{ t("controlUrl") }}<input v-model="tvEditForms[tv.id].control_url" placeholder="http://TV-IP:7676/smp_24_" /></label>
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
                <Edit3 :size="18" />
              </button>
              <button class="icon-button ghost" :title="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :aria-label="tv.autoplay ? t('disableAutoplay') : t('enableAutoplay')" :disabled="isPending(`tv:${tv.id}`)" @click="toggleTvAutoplay(tv)">
                <RefreshCcw :size="18" />
              </button>
              <button class="icon-button ghost" :title="t('detect')" :aria-label="t('detect')" :disabled="isPending(`tv:${tv.id}`)" @click="detectTv(tv)">
                <Search :size="18" />
              </button>
              <button class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" :disabled="isPending(`tv:${tv.id}`)" @click="deleteTv(tv)">
                <Trash2 :size="18" />
              </button>
            </div>
          </div>
        </template>
      </TvCard>
      <div v-if="!status.tvs.length" class="empty">{{ t("noTvs") }}</div>
    </div>
  </section>
</template>
