<script setup>
import {
  Cpu,
  ExternalLink,
  Film,
  History,
  LayoutDashboard,
  ListVideo,
  LogOut,
  Monitor,
  RefreshCw,
  Settings,
  Tv,
  Users,
} from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatClock } from "../utils/time";

const { availableLocales, locale, setLocale, t } = useI18n();
const { activeView, error, isAdmin, liveStatus, logout, refreshAll, session, setActiveView, version } = useScreenloop();

const navItems = [
  { view: "dashboard", label: "dashboard", icon: LayoutDashboard },
  { view: "tvs", label: "tvs", icon: Tv },
  { view: "media", label: "media", icon: Film },
  { view: "playlists", label: "playlists", icon: ListVideo },
  { view: "jobs", label: "transcode", icon: Cpu },
  { view: "events", label: "events", icon: History },
  { view: "users", label: "users", icon: Users },
  { view: "settings", label: "settings", icon: Settings },
];

const visibleNavItems = computed(() => navItems.filter((item) => item.view !== "users" || isAdmin.value));
const title = computed(() => (activeView.value === "dashboard" ? t("tvDashboard") : t(navItems.find((item) => item.view === activeView.value)?.label || "dashboard")));
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
      <div class="brand-mark"><Monitor :size="20" /></div>
      <div>
        <strong>Screenloop</strong>
        <span>{{ t("navSubtitle") }}</span>
      </div>
    </div>
    <nav>
      <button
        v-for="item in visibleNavItems"
        :key="item.view"
        class="nav-link"
        :class="{ active: activeView === item.view }"
        @click="setActiveView(item.view)"
      >
        <component :is="item.icon" :size="18" />
        <span>{{ t(item.label) }}</span>
      </button>
      <a href="/" class="fallback nav-link">
        <ExternalLink :size="18" />
        <span>{{ t("classicUi") }}</span>
      </a>
    </nav>
    <div class="sidebar-foot">
      <span>{{ session.user.username }} / {{ session.user.role }}</span>
      <button class="secondary action-button" @click="logout">
        <LogOut :size="17" />
        <span>{{ t("logout") }}</span>
      </button>
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
        <button class="action-button" @click="refreshAll">
          <RefreshCw :size="17" />
          <span>{{ t("refresh") }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="error banner">{{ error }}</p>
    <slot />
  </section>
</template>
