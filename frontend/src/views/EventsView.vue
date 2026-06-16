<script setup>
import { Clock, RefreshCw } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatUnixTime } from "../utils/time";

const { t } = useI18n();
const { events, loadEvents } = useScreenloop();

const eventTypeFilter = ref("");
const eventTvFilter = ref("");

const eventTypes = computed(() => [...new Set(events.value.map((event) => event.event_type).filter(Boolean))].sort());
const eventTvs = computed(() => [...new Set(events.value.map((event) => String(event.tv_name || event.tv_id || "-")).filter(Boolean))].sort());

const filteredEvents = computed(() => events.value.filter((event) => {
  const tvLabel = String(event.tv_name || event.tv_id || "-");
  return (!eventTypeFilter.value || event.event_type === eventTypeFilter.value)
    && (!eventTvFilter.value || tvLabel === eventTvFilter.value);
}));

function safeEventDetails(details) {
  return String(details || "").replace(/token=[^&\s]+/g, "token=...");
}
</script>

<template>
  <section class="panel">
    <div class="section-head">
      <div>
        <h2>{{ t("recentEvents") }}</h2>
        <p class="muted">{{ t("events") }}: {{ filteredEvents.length }} / {{ events.length }}</p>
      </div>
      <div class="toolbar events-toolbar">
        <select v-model="eventTypeFilter" :aria-label="t('allTypes')">
          <option value="">{{ t("allTypes") }}</option>
          <option v-for="type in eventTypes" :key="type" :value="type">{{ type }}</option>
        </select>
        <select v-model="eventTvFilter" :aria-label="t('allTvs')">
          <option value="">{{ t("allTvs") }}</option>
          <option v-for="tv in eventTvs" :key="tv" :value="tv">{{ tv }}</option>
        </select>
        <button class="ghost action-button" @click="loadEvents">
          <RefreshCw :size="17" />
          <span>{{ t("refreshEvents") }}</span>
        </button>
      </div>
    </div>
    <div class="table events-table">
      <div class="table-row head"><span>{{ t("type") }}</span><span>{{ t("message") }}</span><span>{{ t("tv") }}</span><span>{{ t("time") }}</span></div>
      <div v-for="event in filteredEvents" :key="event.id" class="table-row">
        <span><strong class="event-type">{{ event.event_type }}</strong></span>
        <span>
          {{ event.message }}
          <details v-if="event.details" class="event-details">
            <summary>{{ t("details") }}</summary>
            <code>{{ safeEventDetails(event.details) }}</code>
          </details>
        </span>
        <span>{{ event.tv_name || event.tv_id || "-" }}</span>
        <span class="inline-status"><Clock :size="15" />{{ formatUnixTime(event.created_at) }}</span>
      </div>
      <div v-if="!filteredEvents.length" class="empty">{{ t("noEventsShort") }}</div>
    </div>
  </section>
</template>
