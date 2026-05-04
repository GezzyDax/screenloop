<script setup>
import { computed, onMounted, onUnmounted } from "vue";
import AppShell from "./components/AppShell.vue";
import LoginScreen from "./components/LoginScreen.vue";
import { useScreenloop } from "./store/screenloop";
import DashboardView from "./views/DashboardView.vue";
import EventsView from "./views/EventsView.vue";
import MediaView from "./views/MediaView.vue";
import PlaylistsView from "./views/PlaylistsView.vue";
import TranscodeView from "./views/TranscodeView.vue";
import TvsView from "./views/TvsView.vue";

const { activeView, boot, isAuthed, stopPolling } = useScreenloop();

const views = {
  dashboard: DashboardView,
  tvs: TvsView,
  media: MediaView,
  playlists: PlaylistsView,
  jobs: TranscodeView,
  events: EventsView,
};

const currentView = computed(() => views[activeView.value] || DashboardView);

onMounted(boot);
onUnmounted(stopPolling);
</script>

<template>
  <main class="shell">
    <LoginScreen v-if="!isAuthed" />
    <template v-else>
      <AppShell>
        <component :is="currentView" />
      </AppShell>
    </template>
  </main>
</template>
