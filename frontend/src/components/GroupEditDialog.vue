<script setup>
// Editing in the row itself meant four clicks for a rename, a layout jump when
// the row turned into a form, and a <button> nested inside a <button>. The tree
// is now a plain filter and editing happens here, matching the TV dialog --
// which also leaves somewhere for per-group operating hours to go later.
import { FolderTree, Trash2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  createGroup,
  creatingGroup,
  deleteGroup,
  editingGroup,
  groupDraft,
  groupForm,
  groups,
  isPending,
  saveGroupEdit,
  stopGroupCreate,
  stopGroupEdit,
} = useScreenloop();

const creating = computed(() => creatingGroup.value);
const open = computed(() => creating.value || editingGroup.value !== null);
const draft = computed(() => (creating.value ? groupForm.value : groupDraft.value));

function close() {
  if (creating.value) stopGroupCreate();
  else stopGroupEdit();
}

function submit() {
  if (creating.value) createGroup();
  else saveGroupEdit();
}

const busy = computed(() => (editingGroup.value ? isPending(`group:${editingGroup.value.id}`) : false));

// A group cannot be moved inside itself or anything below it, and the backend
// refuses it anyway; hiding those options avoids offering a guaranteed error.
const descendants = computed(() => {
  const group = editingGroup.value;
  if (!group) return new Set();
  const blocked = new Set([group.id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const candidate of groups.value) {
      if (candidate.parent_id && blocked.has(candidate.parent_id) && !blocked.has(candidate.id)) {
        blocked.add(candidate.id);
        grew = true;
      }
    }
  }
  return blocked;
});

const parentOptions = computed(() => groups.value.filter((group) => !descendants.value.has(group.id)));
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="close">
    <div class="modal group-edit" role="dialog" aria-modal="true">
      <header class="tv-edit-head">
        <div class="section-title">
          <FolderTree :size="15" />
          <div>
            <h3>{{ creating ? t("addGroup") : t("editGroup") }}</h3>
            <p v-if="editingGroup" class="muted">{{ editingGroup.path }} · {{ t("tvs") }}: {{ editingGroup.tv_count }}</p>
            <p v-else class="muted">{{ t("groupsAsideHint") }}</p>
          </div>
        </div>
      </header>

      <form class="tv-edit-form" @submit.prevent="submit()">
        <fieldset>
          <legend>{{ t("groupName") }}</legend>
          <div class="field-grid">
            <label>{{ t("name") }}<input v-model="draft.name" required maxlength="128" autofocus /></label>
            <label>{{ t("groupParent") }}
              <select v-model="draft.parent_id">
                <option value="">{{ t("groupRoot") }}</option>
                <option v-for="group in parentOptions" :key="group.id" :value="group.id">{{ group.path }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <footer class="tv-edit-actions">
          <button
            v-if="editingGroup"
            type="button"
            class="icon-button ghost"
            :title="t('delete')"
            :disabled="busy"
            @click="deleteGroup(editingGroup)"
          >
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
