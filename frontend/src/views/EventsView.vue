<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { events, loadEvents } = useScreenloop();
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <h2>{{ t("recentEvents") }}</h2>
      <button class="ghost" @click="loadEvents">{{ t("refreshEvents") }}</button>
    </div>
    <div class="table events-table">
      <div class="table-row head"><span>{{ t("type") }}</span><span>{{ t("message") }}</span><span>{{ t("tv") }}</span><span>{{ t("time") }}</span></div>
      <div v-for="event in events" :key="event.id" class="table-row">
        <span><strong>{{ event.event_type }}</strong></span>
        <span>{{ event.message }}<small>{{ event.details }}</small></span>
        <span>{{ event.tv_name || event.tv_id || "-" }}</span>
        <span>{{ event.created_at }}</span>
      </div>
    </div>
  </section>
</template>
