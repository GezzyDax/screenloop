<script setup>
import { RotateCcw, Search, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t, tOr } = useI18n();
const { canOperate, cleanupTranscode, isAdmin, isPending, rebuildJob, status, statusClass } = useScreenloop();

const PAGE_SIZE = 50;
const query = ref("");
const statusFilter = ref("");
const shownCount = ref(PAGE_SIZE);

const jobStatuses = computed(() => [...new Set(status.value.transcode_jobs.map((job) => job.status))].sort());

const filteredJobs = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return status.value.transcode_jobs.filter(
    (job) =>
      (!statusFilter.value || job.status === statusFilter.value)
      && (!needle || job.title.toLowerCase().includes(needle) || (job.original_name || "").toLowerCase().includes(needle)),
  );
});

const visibleJobs = computed(() => filteredJobs.value.slice(0, shownCount.value));
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <div>
        <h2>{{ t("transcodeJobs") }}</h2>
        <p class="muted">{{ t("jobs") }}: {{ status.transcode_jobs.length }}</p>
      </div>
      <button v-if="isAdmin" class="ghost action-button" :disabled="isPending('transcode:cleanup')" @click="cleanupTranscode">
        <Trash2 :size="17" />
        <span>{{ t("cleanCache") }}</span>
      </button>
    </div>
    <div class="toolbar">
      <label class="search-field">
        <Search :size="16" />
        <input v-model="query" type="search" :placeholder="t('searchPlaceholder')" :aria-label="t('searchPlaceholder')" />
      </label>
      <select v-model="statusFilter" :aria-label="t('status')">
        <option value="">{{ t("allTypes") }}</option>
        <option v-for="item in jobStatuses" :key="item" :value="item">{{ tOr(`jobStatus_${item}`, item) }}</option>
      </select>
    </div>
    <div class="table">
      <div class="table-row head"><span>{{ t("media") }}</span><span>{{ t("profile") }}</span><span>{{ t("status") }}</span><span>{{ t("actions") }}</span></div>
      <div v-for="job in visibleJobs" :key="job.id" class="table-row">
        <span><strong>{{ job.title }}</strong><small>{{ job.original_name }}</small></span>
        <span>{{ job.profile }}</span>
        <span><b class="status-pill" :class="statusClass(job.status)">{{ tOr(`jobStatus_${job.status}`, job.status) }}</b></span>
        <span class="row-actions">
          <button v-if="canOperate" class="icon-button ghost" :title="t('rebuild')" :aria-label="t('rebuild')" :disabled="isPending(`job:${job.id}`)" @click="rebuildJob(job)">
            <RotateCcw :size="18" />
          </button>
        </span>
      </div>
      <div v-if="!filteredJobs.length" class="empty">{{ t("emptyJobs") }}</div>
    </div>
    <div v-if="filteredJobs.length > visibleJobs.length" class="show-more">
      <span class="muted">{{ t("shownOf", { shown: visibleJobs.length, total: filteredJobs.length }) }}</span>
      <button class="ghost" @click="shownCount += PAGE_SIZE">{{ t("showMore") }}</button>
    </div>
  </section>
</template>
