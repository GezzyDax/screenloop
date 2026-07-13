<script setup>
import { CheckCircle2, X, XCircle } from "@lucide/vue";
import { useScreenloop } from "../store/screenloop";

const { toasts, dismissToast } = useScreenloop();
</script>

<template>
  <div class="toast-stack" aria-live="polite">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.kind">
      <CheckCircle2 v-if="toast.kind === 'success'" :size="15" />
      <XCircle v-else :size="15" />
      <span>{{ toast.text }}</span>
      <button class="toast-close" :aria-label="'×'" @click="dismissToast(toast.id)">
        <X :size="13" />
      </button>
    </div>
  </div>
</template>
