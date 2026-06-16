<script setup>
import { Clock, RefreshCw } from "@lucide/vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatUnixTime } from "../utils/time";

const { t } = useI18n();
const { events, loadEvents } = useScreenloop();
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <div>
        <h2>{{ t("recentEvents") }}</h2>
        <p class="muted">{{ t("events") }}: {{ events.length }}</p>
      </div>
      <button class="ghost action-button" @click="loadEvents">
        <RefreshCw :size="17" />
        <span>{{ t("refreshEvents") }}</span>
      </button>
    </div>
    <div class="table events-table">
      <div class="table-row head"><span>{{ t("type") }}</span><span>{{ t("message") }}</span><span>{{ t("tv") }}</span><span>{{ t("time") }}</span></div>
      <div v-for="event in events" :key="event.id" class="table-row">
        <span><strong class="event-type">{{ event.event_type }}</strong></span>
        <span>{{ event.message }}<small>{{ event.details }}</small></span>
        <span>{{ event.tv_name || event.tv_id || "-" }}</span>
        <span class="inline-status"><Clock :size="15" />{{ formatUnixTime(event.created_at) }}</span>
      </div>
      <div v-if="!events.length" class="empty">{{ t("noEventsShort") }}</div>
    </div>
  </section>
</template>
