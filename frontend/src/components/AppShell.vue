<script setup>
import {
  Cpu,
  Film,
  History,
  LayoutDashboard,
  ListVideo,
  LogOut,
  Monitor,
  Moon,
  Network,
  RefreshCw,
  Settings,
  Sun,
  Tv,
  UserCircle,
  Users,
} from "@lucide/vue";
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useTheme } from "../composables/theme";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatClock } from "../utils/time";

const { availableLocales, locale, setLocale, t } = useI18n();
const { resolvedTheme, toggleTheme } = useTheme();
const { error, isAdmin, liveStatus, logout, refreshAll, session, version } = useScreenloop();
const route = useRoute();

const navItems = [
  { view: "dashboard", to: "/", label: "dashboard", icon: LayoutDashboard },
  { view: "tvs", to: "/tvs", label: "tvs", icon: Tv },
  { view: "media", to: "/media", label: "media", icon: Film },
  { view: "playlists", to: "/playlists", label: "playlists", icon: ListVideo },
  { view: "jobs", to: "/transcode", label: "transcode", icon: Cpu },
  { view: "events", to: "/events", label: "events", icon: History },
  { view: "nodes", to: "/nodes", label: "nodes", icon: Network, adminOnly: true },
  { view: "users", to: "/users", label: "users", icon: Users, adminOnly: true },
  { view: "profile", to: "/profile", label: "profile", icon: UserCircle },
  { view: "settings", to: "/settings", label: "settings", icon: Settings, adminOnly: true },
];

const visibleNavItems = computed(() => navItems.filter((item) => !item.adminOnly || isAdmin.value));
const title = computed(() => (route.name === "dashboard" ? t("tvDashboard") : t(String(route.meta.label || "dashboard"))));
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
      <router-link
        v-for="item in visibleNavItems"
        :key="item.view"
        :to="item.to"
        class="nav-link"
        :class="{ active: route.name === item.view }"
      >
        <component :is="item.icon" :size="18" />
        <span>{{ t(item.label) }}</span>
      </router-link>
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
        <button class="icon-button ghost" :title="t('toggleTheme')" :aria-label="t('toggleTheme')" @click="toggleTheme">
          <Sun v-if="resolvedTheme() === 'dark'" :size="18" />
          <Moon v-else :size="18" />
        </button>
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
