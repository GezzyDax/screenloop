<script setup>
import { computed } from "vue";
import TvCard from "../components/TvCard.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { failedJobs, readyMedia, runningJobs, status } = useScreenloop();

const pingReachableTvs = computed(() => status.value.tvs.filter((tv) => tv.ping_reachable).length);
const streamingTvs = computed(() => status.value.tvs.filter((tv) => tv.streaming).length);
</script>

<template>
  <section class="content-grid">
    <div class="metric ok">
      <span>{{ t("onlineTvs") }}</span>
      <strong>{{ status.tvs.filter((tv) => tv.online).length }} / {{ status.tvs.length }}</strong>
    </div>
    <div class="metric">
      <span>{{ t("pingReachable") }}</span>
      <strong>{{ pingReachableTvs }} / {{ status.tvs.length }}</strong>
    </div>
    <div class="metric warn">
      <span>{{ t("streamingTvs") }}</span>
      <strong>{{ streamingTvs }}</strong>
    </div>
    <div class="metric bad">
      <span>{{ t("jobs") }}</span>
      <strong>{{ runningJobs.length }} / {{ failedJobs.length }}</strong>
      <small>{{ t("readyMedia") }}: {{ readyMedia.length }}</small>
    </div>
  </section>

  <section class="tv-grid">
    <TvCard v-for="tv in status.tvs" :key="tv.id" :tv="tv" />
    <div v-if="!status.tvs.length" class="empty">{{ t("noTvs") }}</div>
  </section>
</template>
