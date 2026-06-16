<script setup>
import { Activity, AlertTriangle, Film, MonitorCheck, Radio, Wifi } from "@lucide/vue";
import { computed } from "vue";
import TvCard from "../components/TvCard.vue";
import TvDetailsPanel from "../components/TvDetailsPanel.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { failedJobs, readyMedia, runningJobs, status } = useScreenloop();

const onlineTvs = computed(() => status.value.tvs.filter((tv) => tv.online).length);
const pingReachableTvs = computed(() => status.value.tvs.filter((tv) => tv.ping_reachable).length);
const streamingTvs = computed(() => status.value.tvs.filter((tv) => tv.streaming).length);

const metrics = computed(() => [
  { label: t("onlineTvs"), value: `${onlineTvs.value} / ${status.value.tvs.length}`, tone: "ok", icon: MonitorCheck },
  { label: t("pingReachable"), value: `${pingReachableTvs.value} / ${status.value.tvs.length}`, tone: "", icon: Wifi },
  { label: t("streamingTvs"), value: streamingTvs.value, tone: "warn", icon: Radio },
  { label: t("jobs"), value: `${runningJobs.value.length} / ${failedJobs.value.length}`, tone: failedJobs.value.length ? "bad" : "", icon: Activity, note: `${t("readyMedia")}: ${readyMedia.value.length}` },
]);
</script>

<template>
  <section class="content-grid">
    <div v-for="metric in metrics" :key="metric.label" class="metric" :class="metric.tone">
      <span class="metric-icon"><component :is="metric.icon" :size="20" /></span>
      <div>
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small v-if="metric.note">{{ metric.note }}</small>
      </div>
    </div>
  </section>

  <section class="panel dashboard-summary">
    <div class="section-head">
      <div>
        <h2>{{ t("tvDashboard") }}</h2>
        <p class="muted">{{ t("configuredTvs") }}</p>
      </div>
      <span class="pill" :class="failedJobs.length ? 'bad' : 'ok'">
        <AlertTriangle v-if="failedJobs.length" :size="15" />
        <Film v-else :size="15" />
        {{ t("readyMedia") }}: {{ readyMedia.length }}
      </span>
    </div>
  </section>

  <section class="tv-grid">
    <TvCard v-for="tv in status.tvs" :key="tv.id" :tv="tv" />
    <div v-if="!status.tvs.length" class="empty">{{ t("noTvs") }}</div>
  </section>

  <TvDetailsPanel v-if="status.tvs.length" />
</template>
