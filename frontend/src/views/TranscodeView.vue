<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { canOperate, cleanupTranscode, isAdmin, rebuildJob, status, statusClass } = useScreenloop();
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <h2>{{ t("transcodeJobs") }}</h2>
      <button v-if="isAdmin" class="ghost" @click="cleanupTranscode">{{ t("cleanCache") }}</button>
    </div>
    <div class="table">
      <div class="table-row head"><span>{{ t("media") }}</span><span>{{ t("profile") }}</span><span>{{ t("status") }}</span><span>{{ t("actions") }}</span></div>
      <div v-for="job in status.transcode_jobs" :key="job.id" class="table-row">
        <span><strong>{{ job.title }}</strong><small>{{ job.original_name }}</small></span>
        <span>{{ job.profile }}</span>
        <span><b :class="statusClass(job.status)">{{ job.status }}</b></span>
        <span class="row-actions"><button v-if="canOperate" class="ghost" @click="rebuildJob(job)">{{ t("rebuild") }}</button></span>
      </div>
    </div>
  </section>
</template>
