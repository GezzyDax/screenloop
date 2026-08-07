<script setup>
// Editing used to happen inline inside the TV card. The card column is about
// 440px wide, so the fields wrapped into cramped pairs, the profile select was
// clipped, and the card stretched far past its neighbour and tore the grid.
// A dialog gives the form the width it needs and separates the destructive
// action from Save.
import { Trash2, Tv } from "@lucide/vue";
import { computed } from "vue";
import TimeField from "./TimeField.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { cancelEditTv, deleteTv, editingTv, groups, isPending, nodes, saveTv, status, tvEditForms, tvProfiles } =
  useScreenloop();

const form = computed(() => (editingTv.value ? tvEditForms.value[editingTv.value.id] : null));
const busy = computed(() => (editingTv.value ? isPending(`tv:${editingTv.value.id}`) : false));

const WEEKDAYS = [
  { value: 0, key: "mon" },
  { value: 1, key: "tue" },
  { value: 2, key: "wed" },
  { value: 3, key: "thu" },
  { value: 4, key: "fri" },
  { value: 5, key: "sat" },
  { value: 6, key: "sun" },
];

const selectedDays = computed(() =>
  String(form.value?.schedule_days || "")
    .split(",")
    .filter(Boolean)
    .map(Number),
);

function toggleDay(day) {
  const days = new Set(selectedDays.value);
  if (days.has(day)) days.delete(day);
  else days.add(day);
  form.value.schedule_days = [...days].sort((a, b) => a - b).join(",");
}

async function submit() {
  const tv = editingTv.value;
  if (tv) await saveTv(tv);
}

function close() {
  if (editingTv.value) cancelEditTv(editingTv.value);
}
</script>

<template>
  <div v-if="editingTv && form" class="modal-backdrop" @click.self="close">
    <div class="modal modal-wide tv-edit" role="dialog" aria-modal="true">
      <header class="tv-edit-head">
        <div class="section-title">
          <Tv :size="15" />
          <div>
            <h3>{{ t("editTv") }}</h3>
            <p class="muted">{{ editingTv.ip }}<template v-if="editingTv.node_name"> · {{ editingTv.node_name }}</template></p>
          </div>
        </div>
      </header>

      <form class="tv-edit-form" @submit.prevent="submit">
        <fieldset>
          <legend>{{ t("tvIdentity") }}</legend>
          <div class="field-grid">
            <label>{{ t("name") }}<input v-model="form.name" required /></label>
            <label>{{ t("ip") }}
              <input v-model="form.ip" required pattern="^\d{1,3}(\.\d{1,3}){3}$" :title="t('ipFormatHint')" />
            </label>
            <label>{{ t("profile") }}
              <select v-model="form.profile">
                <option v-for="(profile, key) in tvProfiles" :key="key" :value="key">
                  {{ profile.name || key }}{{ profile.source === "custom" ? ` · ${t("templateCustom")}` : "" }}
                </option>
              </select>
            </label>
            <label>{{ t("node") }}
              <select v-model="form.node_id">
                <option value="">{{ t("localNode") }}</option>
                <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>{{ t("playback") }}</legend>
          <div class="field-grid">
            <label>{{ t("playlist") }}
              <select v-model="form.playlist_id">
                <option value="">{{ t("noPlaylist") }}</option>
                <option v-for="playlist in status.playlists" :key="playlist.id" :value="playlist.id">{{ playlist.name }}</option>
              </select>
            </label>
            <label>{{ t("group") }}
              <select v-model="form.group_id">
                <option value="">{{ t("withoutGroup") }}</option>
                <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.path }}</option>
              </select>
            </label>
          </div>
          <label class="check-line">
            <input v-model="form.autoplay" type="checkbox" />
            <span>{{ t("autoplay") }}</span>
          </label>
        </fieldset>

        <fieldset>
          <legend>{{ t("scheduleMode") }}</legend>
          <div class="field-grid">
            <label>{{ t("scheduleMode") }}
              <select v-model="form.schedule_mode">
                <option value="inherit">{{ t("scheduleModeInherit") }}</option>
                <option value="always">{{ t("scheduleModeAlways") }}</option>
                <option value="custom">{{ t("scheduleModeCustom") }}</option>
              </select>
            </label>
          </div>
          <template v-if="form.schedule_mode === 'custom'">
            <div class="day-picker">
              <button
                v-for="day in WEEKDAYS"
                :key="day.value"
                type="button"
                class="day-toggle"
                :class="{ active: selectedDays.includes(day.value) }"
                @click="toggleDay(day.value)"
              >
                {{ t(day.key) }}
              </button>
            </div>
            <div class="time-row">
              <label><span>{{ t("scheduleStart") }}</span><TimeField v-model="form.schedule_start" /></label>
              <label><span>{{ t("scheduleEnd") }}</span><TimeField v-model="form.schedule_end" /></label>
            </div>
          </template>
        </fieldset>

        <fieldset>
          <legend>{{ t("advanced") }}</legend>
          <label class="wide">{{ t("controlUrl") }}
            <input v-model="form.control_url" placeholder="http://TV-IP:7676/smp_24_" />
          </label>
        </fieldset>

        <footer class="tv-edit-actions">
          <button type="button" class="icon-button ghost" :title="t('delete')" :disabled="busy" @click="deleteTv(editingTv)">
            <Trash2 :size="15" />
          </button>
          <span class="spacer"></span>
          <button type="button" class="ghost" @click="close">{{ t("cancel") }}</button>
          <button type="submit" :disabled="busy">{{ t("save") }}</button>
        </footer>
      </form>
    </div>
  </div>
</template>
