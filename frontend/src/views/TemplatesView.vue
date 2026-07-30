<script setup>
import { Download, Link, RefreshCw, Trash2, Upload } from "@lucide/vue";
import { onMounted, ref } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  deleteTemplate,
  importTemplateByUrl,
  installCatalogTemplate,
  isAdmin,
  isPending,
  loadTemplateCatalog,
  loadTemplates,
  templateCatalog,
  templateImportForm,
  templates,
  templatesInUse,
  uploadTemplateFile,
} = useScreenloop();

const fileInput = ref(null);

onMounted(() => {
  loadTemplates().catch(() => {});
  loadTemplateCatalog().catch(() => {});
});

function pickFile(event) {
  const [file] = event.target.files || [];
  uploadTemplateFile(file).finally(() => {
    if (fileInput.value) fileInput.value.value = "";
  });
}
</script>

<template>
  <section v-if="!isAdmin" class="panel">
    <h2>{{ t("templates") }}</h2>
    <p class="muted">{{ t("adminOnlyTemplates") }}</p>
  </section>

  <section v-else class="stack">
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("installedTemplates") }}</h2>
          <p class="muted">{{ t("installedTemplatesHint") }}</p>
        </div>
        <button class="ghost action-button" @click="loadTemplates">
          <RefreshCw :size="14" />
          <span>{{ t("refresh") }}</span>
        </button>
      </div>
      <div class="table templates-table">
        <div class="table-row head">
          <span>{{ t("name") }}</span>
          <span>{{ t("templateSource") }}</span>
          <span>{{ t("templateMatch") }}</span>
          <span>{{ t("actions") }}</span>
        </div>
        <div v-for="template in templates" :key="template.id" class="table-row">
          <span>
            <strong>{{ template.name }}</strong>
            <small class="mono">{{ template.id }}</small>
          </span>
          <span>
            <b class="status-pill" :class="template.source === 'builtin' ? 'ok' : 'warn'">
              {{ template.source === "builtin" ? t("templateBuiltin") : t("templateCustom") }}
            </b>
          </span>
          <span class="mono">{{ template.match.join(", ") || "—" }}</span>
          <span class="row-actions">
            <button
              v-if="template.source === 'custom'"
              class="icon-button danger"
              :title="templatesInUse.includes(template.id) ? t('templateInUseHint') : t('delete')"
              :aria-label="t('delete')"
              :disabled="templatesInUse.includes(template.id) || isPending(`template:${template.id}`)"
              @click="deleteTemplate(template)"
            >
              <Trash2 :size="15" />
            </button>
            <small v-else class="muted">{{ t("templateBuiltinLocked") }}</small>
          </span>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("importTemplate") }}</h2>
          <p class="muted">{{ t("importTemplateHint") }}</p>
        </div>
      </div>
      <form class="inline-form" @submit.prevent="importTemplateByUrl">
        <input v-model="templateImportForm.url" type="url" :placeholder="t('templateUrlPlaceholder')" required />
        <button type="submit" class="action-button" :disabled="isPending('template:import')">
          <Link :size="14" />
          <span>{{ t("importByUrl") }}</span>
        </button>
      </form>
      <div class="upload-row">
        <input ref="fileInput" type="file" accept=".toml" hidden @change="pickFile" />
        <button class="ghost action-button" :disabled="isPending('template:upload')" @click="fileInput?.click()">
          <Upload :size="14" />
          <span>{{ t("uploadTemplateFile") }}</span>
        </button>
      </div>
    </div>

    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("communityCatalog") }}</h2>
          <p class="muted">{{ t("communityCatalogHint") }}</p>
        </div>
        <button v-if="templateCatalog.enabled" class="ghost action-button" @click="loadTemplateCatalog">
          <RefreshCw :size="14" />
          <span>{{ t("refresh") }}</span>
        </button>
      </div>

      <p v-if="!templateCatalog.enabled" class="empty">{{ t("communityCatalogDisabled") }}</p>
      <p v-else-if="templateCatalog.error" class="empty">{{ t("communityCatalogError") }}: {{ templateCatalog.error }}</p>
      <p v-else-if="!templateCatalog.entries.length" class="empty">{{ t("communityCatalogEmpty") }}</p>
      <div v-else class="table templates-table">
        <div class="table-row head">
          <span>{{ t("name") }}</span>
          <span>{{ t("templateVendor") }}</span>
          <span>{{ t("templateAuthor") }}</span>
          <span>{{ t("actions") }}</span>
        </div>
        <div v-for="entry in templateCatalog.entries" :key="entry.id" class="table-row">
          <span>
            <strong>{{ entry.name }}</strong>
            <small>{{ entry.description || entry.id }}</small>
          </span>
          <span>{{ entry.vendor || "—" }}</span>
          <span>{{ entry.author || "—" }}</span>
          <span class="row-actions">
            <button
              class="icon-button ghost"
              :title="entry.installed ? t('templateAlreadyInstalled') : t('install')"
              :aria-label="t('install')"
              :disabled="entry.installed || isPending(`template:${entry.id}`)"
              @click="installCatalogTemplate(entry)"
            >
              <Download :size="15" />
            </button>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.templates-table .table-row {
  grid-template-columns: 2fr 1fr 2fr auto;
}

.upload-row {
  margin-top: 12px;
}
</style>
