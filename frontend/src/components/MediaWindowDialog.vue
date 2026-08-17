<script setup>
// Dating a campaign across a selection. A window is two fields and a warning
// about how many clips it lands on, which is more than a confirmation box can
// carry -- so it gets a dialog of its own rather than being squeezed into the
// bulk bar as two loose inputs.
import { CalendarClock } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const props = defineProps({ open: Boolean });
const emit = defineEmits(["close"]);

const { t } = useI18n();
const { bulkSetWindow, isPending, mediaSelection } = useScreenloop();

const startsAt = ref("");
const expiresAt = ref("");
const error = ref("");

// Opening on a fresh selection starts from blank rather than from whatever was
// typed last time: a stale date silently applied to twenty clips is exactly the
// kind of accident this dialog exists to prevent.
watch(
  () => props.open,
  (open) => {
    if (!open) return;
    startsAt.value = "";
    expiresAt.value = "";
    error.value = "";
  },
);

async function apply() {
  if (startsAt.value && expiresAt.value && new Date(startsAt.value) >= new Date(expiresAt.value)) {
    error.value = t("mediaWindowInverted");
    return;
  }
  await bulkSetWindow(startsAt.value, expiresAt.value);
  emit("close");
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
    <div class="modal modal-window" role="dialog" aria-modal="true">
      <div class="section-title">
        <CalendarClock :size="15" />
        <h3>{{ t("mediaWindowDialogTitle") }}</h3>
      </div>
      <p>{{ t("mediaWindowDialogText", { count: mediaSelection.length }) }}</p>

      <div class="field-grid">
        <label>{{ t("mediaStartsAt") }}
          <input v-model="startsAt" type="datetime-local" />
          <small class="muted">{{ t("mediaStartsHint") }}</small>
        </label>
        <label>{{ t("mediaExpiresAt") }}
          <input v-model="expiresAt" type="datetime-local" />
          <small class="muted">{{ t("mediaExpiresHint") }}</small>
        </label>
      </div>
      <p v-if="error" class="error-text">{{ error }}</p>
      <!-- Clearing both is a real intention -- taking dates off a finished
           campaign -- so it is spelled out rather than disabled. -->
      <p v-else-if="!startsAt && !expiresAt" class="muted">{{ t("mediaWindowClearNote") }}</p>

      <div class="row-actions modal-actions">
        <button :disabled="isPending('media:bulk')" @click="apply">{{ t("apply") }}</button>
        <button class="ghost" @click="emit('close')">{{ t("cancel") }}</button>
      </div>
    </div>
  </div>
</template>
