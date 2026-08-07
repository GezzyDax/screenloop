<script setup>
// Adding a TV used to be a permanently visible five-field form at the top of
// the page, taking a band of screen whether or not anybody was adding
// anything. It is an occasional action, so it lives behind a button now.
import { Plus, Tv } from "@lucide/vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { createTv, creatingTv, groups, isPending, nodes, stopTvCreate, tvForm, tvProfiles } = useScreenloop();
</script>

<template>
  <div v-if="creatingTv" class="modal-backdrop" @click.self="stopTvCreate">
    <div class="modal group-edit" role="dialog" aria-modal="true">
      <header class="tv-edit-head">
        <div class="section-title">
          <Tv :size="15" />
          <div>
            <h3>{{ t("addTv") }}</h3>
            <p class="muted">{{ t("addTvHint") }}</p>
          </div>
        </div>
      </header>

      <form class="tv-edit-form" @submit.prevent="createTv()">
        <fieldset>
          <legend>{{ t("tvIdentity") }}</legend>
          <div class="field-grid">
            <label>{{ t("name") }}<input v-model="tvForm.name" :placeholder="t('tvNamePlaceholder')" required /></label>
            <label>{{ t("ip") }}
              <input
                v-model="tvForm.ip"
                placeholder="192.168.1.50"
                required
                pattern="^\d{1,3}(\.\d{1,3}){3}$"
                :title="t('ipFormatHint')"
              />
            </label>
            <label>{{ t("profile") }}
              <select v-model="tvForm.profile">
                <option v-for="(profile, key) in tvProfiles" :key="key" :value="key">
                  {{ profile.name || key }}{{ profile.source === "custom" ? ` · ${t("templateCustom")}` : "" }}
                </option>
              </select>
            </label>
            <label>{{ t("node") }}
              <select v-model="tvForm.node_id">
                <option value="">{{ t("localNode") }}</option>
                <option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option>
              </select>
            </label>
            <label>{{ t("group") }}
              <select v-model="tvForm.group_id">
                <option value="">{{ t("withoutGroup") }}</option>
                <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.path }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <footer class="tv-edit-actions">
          <span class="spacer"></span>
          <button type="button" class="ghost" @click="stopTvCreate">{{ t("cancel") }}</button>
          <button type="submit" :disabled="isPending('tv:create')">
            <Plus :size="14" />
            <span>{{ t("addTv") }}</span>
          </button>
        </footer>
      </form>
    </div>
  </div>
</template>
