<script setup>
import TvCard from "../components/TvCard.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { failedJobs, readyMedia, runningJobs, status } = useScreenloop();
</script>

<template>
  <section class="content-grid">
    <div class="metric ok">
      <span>{{ t("onlineTvs") }}</span>
      <strong>{{ status.tvs.filter((tv) => tv.online).length }} / {{ status.tvs.length }}</strong>
    </div>
    <div class="metric">
      <span>{{ t("readyMedia") }}</span>
      <strong>{{ readyMedia.length }}</strong>
    </div>
    <div class="metric warn">
      <span>{{ t("runningJobs") }}</span>
      <strong>{{ runningJobs.length }}</strong>
    </div>
    <div class="metric bad">
      <span>{{ t("failedJobs") }}</span>
      <strong>{{ failedJobs.length }}</strong>
    </div>
  </section>

  <section class="tv-grid">
    <TvCard v-for="tv in status.tvs" :key="tv.id" :tv="tv" />
    <div v-if="!status.tvs.length" class="empty">{{ t("noTvs") }}</div>
  </section>
</template>
