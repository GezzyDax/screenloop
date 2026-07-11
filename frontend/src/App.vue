<script setup>
import { computed, onMounted, onUnmounted } from "vue";
import AppShell from "./components/AppShell.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import LoginScreen from "./components/LoginScreen.vue";
import ToastStack from "./components/ToastStack.vue";
import { useI18n } from "./i18n";
import { useScreenloop } from "./store/screenloop";
import DashboardView from "./views/DashboardView.vue";
import EventsView from "./views/EventsView.vue";
import MediaView from "./views/MediaView.vue";
import PlaylistsView from "./views/PlaylistsView.vue";
import ProfileView from "./views/ProfileView.vue";
import SettingsView from "./views/SettingsView.vue";
import TranscodeView from "./views/TranscodeView.vue";
import TvsView from "./views/TvsView.vue";
import UsersView from "./views/UsersView.vue";

const { t } = useI18n();
const { activeView, boot, isAuthed, loading, stopPolling } = useScreenloop();

const views = {
  dashboard: DashboardView,
  tvs: TvsView,
  media: MediaView,
  playlists: PlaylistsView,
  jobs: TranscodeView,
  events: EventsView,
  users: UsersView,
  profile: ProfileView,
  settings: SettingsView,
};

const currentView = computed(() => views[activeView.value] || DashboardView);

onMounted(boot);
onUnmounted(stopPolling);
</script>

<template>
  <main class="shell">
    <div v-if="loading && !isAuthed" class="splash">{{ t("sessionCheck") }}</div>
    <LoginScreen v-else-if="!isAuthed" />
    <template v-else>
      <AppShell>
        <component :is="currentView" />
      </AppShell>
    </template>
    <ToastStack />
    <ConfirmDialog />
  </main>
</template>
