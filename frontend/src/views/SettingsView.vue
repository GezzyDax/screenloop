<script setup>
import { Activity, Database, ExternalLink, HardDrive, Network, ShieldCheck, Terminal, Wrench } from "@lucide/vue";
import { computed, onMounted } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";

const { t } = useI18n();
const { diagnostics, isAdmin, loadDiagnostics, version } = useScreenloop();

const securityWarnings = computed(() => {
  const data = diagnostics.value;
  if (!data) return [];
  const warnings = [];
  if (!data.network?.allowed_tv_cidrs?.length) warnings.push(t("warningAllowedCidrs"));
  if (!data.config?.cookie_secure) warnings.push(t("warningCookieSecure"));
  if (!data.config?.update_check) warnings.push(t("warningUpdateCheck"));
  if (String(data.app?.version || "").includes("dev")) warnings.push(t("warningDevVersion"));
  return warnings;
});

const appFacts = computed(() => {
  const app = diagnostics.value?.app || {};
  return [
    [t("version"), app.version || version.value?.version || "-"],
    [t("revision"), app.revision || version.value?.revision || "-"],
    [t("author"), app.author || version.value?.author || "-"],
    [t("repository"), app.repository || version.value?.repository || "-"],
    [t("host"), app.hostname || "-"],
    [t("platform"), app.platform || "-"],
    [t("python"), app.python || "-"],
  ];
});

const networkFacts = computed(() => {
  const network = diagnostics.value?.network || {};
  return [
    [t("advertiseHosts"), (network.advertise_hosts || []).join(", ") || "-"],
    [t("allowedTvCidrs"), (network.allowed_tv_cidrs || []).join(", ") || "-"],
    [t("trustedProxies"), (network.trusted_proxy_cidrs || []).join(", ") || "-"],
  ];
});

function boolText(value) {
  return value ? t("enabled") : t("disabled");
}

function configText(key, value) {
  if (typeof value === "boolean") return boolText(value);
  if (String(key).endsWith("_bytes")) return formatBytes(value);
  return value;
}

function probeClass(probe) {
  if (probe?.status === "host_managed") return "warn";
  return probe?.ok ? "ok" : "bad";
}

function storageRows() {
  const storage = diagnostics.value?.storage || {};
  const paths = diagnostics.value?.paths || {};
  return Object.entries(storage)
    .filter(([name]) => name !== "data_disk")
    .map(([name, item]) => ({
      name,
      path: paths[name === "database" ? "db_path" : name] || "-",
      size: formatBytes(item?.bytes),
      ok: item?.ok !== false,
    }));
}

function probeText(probe) {
  return (probe?.output || []).join(" | ") || (probe?.ok ? t("enabled") : t("disabled"));
}

onMounted(() => {
  loadDiagnostics().catch(() => {});
});
</script>

<template>
  <section v-if="!isAdmin" class="panel">
    <h2>{{ t("settings") }}</h2>
    <p class="muted">{{ t("adminOnlySettings") }}</p>
  </section>

  <section v-else-if="!diagnostics" class="panel">
    <h2>{{ t("settings") }}</h2>
    <p class="muted">{{ t("loadingDiagnostics") }}</p>
  </section>

  <section v-else class="stack">
    <div class="panel security-panel">
      <div class="section-head">
        <div class="section-title">
          <ShieldCheck :size="21" />
          <div>
            <h2>{{ t("securityCenter") }}</h2>
            <p class="muted">{{ t("diagnostics") }}</p>
          </div>
        </div>
        <a class="button-link ghost" href="/api/v1/diagnostics">
          <ExternalLink :size="17" />
          <span>{{ t("diagnostics") }}</span>
        </a>
      </div>
      <div v-if="securityWarnings.length" class="warning-list">
        <strong>{{ t("securityWarnings") }}</strong>
        <p v-for="warning in securityWarnings" :key="warning" class="warning-item">{{ warning }}</p>
      </div>
      <div v-else class="empty ok">{{ t("securityOk") }}</div>
    </div>

    <div class="settings-grid">
      <article class="panel">
        <div class="section-title compact"><Activity :size="19" /><h2>{{ t("runtime") }}</h2></div>
        <div class="facts-list">
          <div v-for="[label, value] in appFacts" :key="label" class="fact-line">
            <span>{{ label }}</span>
            <strong class="mono">{{ value }}</strong>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="section-title compact"><Database :size="19" /><h2>{{ t("counts") }}</h2></div>
        <div class="facts-list">
          <div v-for="(value, key) in diagnostics.counts" :key="key" class="fact-line">
            <span>{{ key }}</span>
            <strong>{{ value }}</strong>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="section-title compact"><Wrench :size="19" /><h2>{{ t("workers") }}</h2></div>
        <div class="status-row">
          <span v-for="(value, key) in diagnostics.workers" :key="key" :class="value ? 'ok' : 'bad'">{{ key }}</span>
        </div>
      </article>

      <article class="panel">
        <div class="section-title compact"><Terminal :size="19" /><h2>{{ t("probes") }}</h2></div>
        <div class="facts-list">
          <div v-for="(probe, key) in diagnostics.probes" :key="key" class="fact-line">
            <span>{{ key }}</span>
            <strong :class="probeClass(probe)">{{ probeText(probe) }}</strong>
          </div>
        </div>
      </article>
    </div>

    <div class="panel">
      <div class="section-title compact"><Network :size="19" /><h2>{{ t("network") }}</h2></div>
      <div class="facts-list">
        <div v-for="[label, value] in networkFacts" :key="label" class="fact-line">
          <span>{{ label }}</span>
          <strong class="mono">{{ value }}</strong>
        </div>
      </div>
      <div class="table settings-table">
        <div class="table-row head"><span>{{ t("interfaces") }}</span><span>{{ t("ip") }}</span><span>{{ t("status") }}</span><span>{{ t("type") }}</span></div>
        <div v-for="iface in diagnostics.network.interfaces" :key="`${iface.name}-${iface.address}`" class="table-row">
          <span><strong>{{ iface.name }}</strong></span>
          <span class="mono">{{ iface.address }}</span>
          <span>{{ t("enabled") }}</span>
          <span>{{ iface.family }}</span>
        </div>
      </div>
    </div>

    <div class="settings-grid">
      <article class="panel">
        <div class="section-title compact"><HardDrive :size="19" /><h2>{{ t("storage") }}</h2></div>
        <div class="facts-list">
          <div class="fact-line">
            <span>{{ t("free") }}</span>
            <strong>{{ formatBytes(diagnostics.storage.data_disk.free) }}</strong>
          </div>
          <div class="fact-line">
            <span>{{ t("total") }}</span>
            <strong>{{ formatBytes(diagnostics.storage.data_disk.total) }}</strong>
          </div>
          <div v-for="row in storageRows()" :key="row.name" class="fact-line">
            <span>{{ row.name }}</span>
            <strong><span class="mono">{{ row.path }}</span><small>{{ row.size }}</small></strong>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="section-title compact"><ShieldCheck :size="19" /><h2>{{ t("safeConfig") }}</h2></div>
        <div class="facts-list">
          <div v-for="(value, key) in diagnostics.config" :key="key" class="fact-line">
            <span>{{ key }}</span>
            <strong class="mono">{{ configText(key, value) }}</strong>
          </div>
        </div>
      </article>
    </div>

    <div class="panel">
      <div class="section-title compact"><Wrench :size="19" /><h2>{{ t("updates") }}</h2></div>
      <div class="command-grid">
        <div>
          <span>{{ t("stableUpdateCommand") }}</span>
          <code>cd /opt/screenloop &amp;&amp; sudo ./update.sh --main</code>
        </div>
        <div>
          <span>{{ t("devUpdateCommand") }}</span>
          <code>cd /opt/screenloop &amp;&amp; sudo ./update.sh --dev</code>
        </div>
      </div>
      <div class="row-actions docs-actions">
        <a class="button-link" href="/docs"><ExternalLink :size="17" /><span>{{ t("openApiDocs") }}</span></a>
        <a class="button-link ghost" href="/redoc"><ExternalLink :size="17" /><span>{{ t("openRedoc") }}</span></a>
      </div>
    </div>
  </section>
</template>
