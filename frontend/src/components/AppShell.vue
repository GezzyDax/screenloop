<script setup>
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { availableLocales, locale, setLocale, t } = useI18n();
const { activeView, error, logout, refreshAll, session, setActiveView, version } = useScreenloop();

const navItems = [
  ["dashboard", "dashboard"],
  ["tvs", "tvs"],
  ["media", "media"],
  ["playlists", "playlists"],
  ["jobs", "transcode"],
  ["events", "events"],
];

const title = computed(() => (activeView.value === "dashboard" ? t("tvDashboard") : t(navItems.find(([view]) => view === activeView.value)?.[1] || "dashboard")));
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
        v-for="[view, label] in navItems"
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
        <span class="pill">{{ version?.version || "dev" }}</span>
        <span v-if="version?.update_available" class="pill warn">{{ t("update", { version: version.latest_version }) }}</span>
        <button @click="refreshAll">{{ t("refresh") }}</button>
      </div>
    </header>

    <p v-if="error" class="error banner">{{ error }}</p>
    <slot />
  </section>
</template>
