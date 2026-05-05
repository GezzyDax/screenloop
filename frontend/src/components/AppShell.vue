<script setup>
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatClock } from "../utils/time";

const { availableLocales, locale, setLocale, t } = useI18n();
const { activeView, error, isAdmin, liveStatus, logout, refreshAll, session, setActiveView, version } = useScreenloop();

const navItems = [
  ["dashboard", "dashboard"],
  ["tvs", "tvs"],
  ["media", "media"],
  ["playlists", "playlists"],
  ["jobs", "transcode"],
  ["events", "events"],
  ["users", "users"],
  ["settings", "settings"],
];

const visibleNavItems = computed(() => navItems.filter(([view]) => view !== "users" || isAdmin.value));
const title = computed(() => (activeView.value === "dashboard" ? t("tvDashboard") : t(navItems.find(([view]) => view === activeView.value)?.[1] || "dashboard")));
const liveClass = computed(() => (liveStatus.value.statusError ? "bad" : "ok"));
const liveText = computed(() => {
  if (liveStatus.value.statusError) return t("liveUpdateError");
  if (!liveStatus.value.lastStatusAt) return t("liveUpdating");
  return t("updatedAtTime", { time: formatClock(liveStatus.value.lastStatusAt) });
});
</script>

<template>
  <aside class="sidebar">
    <div class="brand-row compact">
      <div class="brand-mark" />
      <div>
        <strong>Screenloop</strong>
        <span>{{ t("navSubtitle") }}</span>
      </div>
    </div>
    <nav>
      <button
        v-for="[view, label] in visibleNavItems"
        :key="view"
        :class="{ active: activeView === view }"
        @click="setActiveView(view)"
      >
        {{ t(label) }}
      </button>
      <a href="/" class="fallback">{{ t("classicUi") }}</a>
    </nav>
    <div class="sidebar-foot">
      <span>{{ session.user.username }} / {{ session.user.role }}</span>
      <button @click="logout">{{ t("logout") }}</button>
    </div>
  </aside>

  <section class="workspace">
    <header class="topbar">
      <div>
        <p class="eyebrow">{{ t("liveControl") }}</p>
        <h1>{{ title }}</h1>
      </div>
      <div class="top-actions">
        <label class="language-switch">
          <span>{{ t("language") }}</span>
          <select :value="locale" @change="setLocale($event.target.value)">
            <option v-for="item in availableLocales" :key="item" :value="item">{{ item.toUpperCase() }}</option>
          </select>
        </label>
        <span class="pill" :class="liveClass">{{ liveText }}</span>
        <span class="pill">{{ version?.version || "dev" }}</span>
        <span v-if="version?.update_available" class="pill warn">{{ t("update", { version: version.latest_version }) }}</span>
        <button @click="refreshAll">{{ t("refresh") }}</button>
      </div>
    </header>

    <p v-if="error" class="error banner">{{ error }}</p>
    <slot />
  </section>
</template>
