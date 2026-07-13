<script setup>
import { RotateCcw, Trash2 } from "@lucide/vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { canOperate, cleanupTranscode, isAdmin, rebuildJob, status, statusClass } = useScreenloop();
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <div>
        <h2>{{ t("transcodeJobs") }}</h2>
        <p class="muted">{{ t("jobs") }}: {{ status.transcode_jobs.length }}</p>
      </div>
      <button v-if="isAdmin" class="ghost action-button" @click="cleanupTranscode">
        <Trash2 :size="17" />
        <span>{{ t("cleanCache") }}</span>
      </button>
    </div>
    <div class="table">
      <div class="table-row head"><span>{{ t("media") }}</span><span>{{ t("profile") }}</span><span>{{ t("status") }}</span><span>{{ t("actions") }}</span></div>
      <div v-for="job in status.transcode_jobs" :key="job.id" class="table-row">
        <span><strong>{{ job.title }}</strong><small>{{ job.original_name }}</small></span>
        <span>{{ job.profile }}</span>
        <span><b class="status-pill" :class="statusClass(job.status)">{{ job.status }}</b></span>
        <span class="row-actions">
          <button v-if="canOperate" class="icon-button ghost" :title="t('rebuild')" :aria-label="t('rebuild')" @click="rebuildJob(job)">
            <RotateCcw :size="18" />
          </button>
        </span>
      </div>
      <div v-if="!status.transcode_jobs.length" class="empty">{{ t("jobs") }}: 0</div>
    </div>
  </section>
</template>
