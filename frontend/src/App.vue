<script setup>
import { onMounted, onUnmounted } from "vue";
import AppShell from "./components/AppShell.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import LoginScreen from "./components/LoginScreen.vue";
import ToastStack from "./components/ToastStack.vue";
import { useI18n } from "./i18n";
import { useScreenloop } from "./store/screenloop";

const { t } = useI18n();
const { boot, isAuthed, loading, stopPolling } = useScreenloop();

onMounted(boot);
onUnmounted(stopPolling);
</script>

<template>
  <main class="shell">
    <div v-if="loading && !isAuthed" class="splash">{{ t("sessionCheck") }}</div>
    <LoginScreen v-else-if="!isAuthed" />
    <template v-else>
      <AppShell>
        <router-view />
      </AppShell>
    </template>
    <ToastStack />
    <ConfirmDialog />
  </main>
</template>
