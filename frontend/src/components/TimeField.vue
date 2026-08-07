<script setup>
// `<input type="time">` renders in the *browser's* locale, not the page's, so
// an en-US browser shows "08:00 AM" no matter what the panel is set to and no
// attribute changes it. Operating hours are read off a wall clock in a
// European office, so the field is built from two selects instead: always
// 24-hour, and nothing to mistype.
import { computed } from "vue";

const props = defineProps({
  modelValue: { type: String, default: "00:00" },
  disabled: { type: Boolean, default: false },
  minuteStep: { type: Number, default: 5 },
});
const emit = defineEmits(["update:modelValue"]);

const HOURS = Array.from({ length: 24 }, (_, index) => String(index).padStart(2, "0"));

const minutes = computed(() => {
  const step = Math.max(1, props.minuteStep);
  const values = [];
  for (let value = 0; value < 60; value += step) values.push(String(value).padStart(2, "0"));
  // Keep a value that does not sit on the step, so an existing 08:07 is not
  // silently rounded away when the form opens.
  const current = parts.value.minute;
  if (!values.includes(current)) values.push(current);
  return values.sort();
});

const parts = computed(() => {
  const [hour = "00", minute = "00"] = String(props.modelValue || "00:00").split(":");
  return { hour: hour.padStart(2, "0"), minute: minute.padStart(2, "0") };
});

function update(part, value) {
  const next = { ...parts.value, [part]: value };
  emit("update:modelValue", `${next.hour}:${next.minute}`);
}
</script>

<template>
  <span class="time-field">
    <select :value="parts.hour" :disabled="disabled" aria-label="hours" @change="update('hour', $event.target.value)">
      <option v-for="hour in HOURS" :key="hour" :value="hour">{{ hour }}</option>
    </select>
    <b>:</b>
    <select :value="parts.minute" :disabled="disabled" aria-label="minutes" @change="update('minute', $event.target.value)">
      <option v-for="minute in minutes" :key="minute" :value="minute">{{ minute }}</option>
    </select>
  </span>
</template>
