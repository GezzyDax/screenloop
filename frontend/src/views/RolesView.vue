<script setup>
import { KeyRound, Lock, Plus, Trash2 } from "@lucide/vue";
import { computed, onMounted } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const {
  beginEditRole,
  can,
  deleteRole,
  isPending,
  loadRoles,
  permissionCatalog,
  roleForm,
  roles,
  saveRole,
  toggleRolePermission,
} = useScreenloop();

const mayManage = computed(() => can("role.manage"));

// The catalogue arrives flat and ordered; grouping it here keeps the ordering
// the backend chose rather than inventing a second one in the UI.
const sections = computed(() => {
  const grouped = new Map();
  for (const permission of permissionCatalog.value) {
    if (!grouped.has(permission.section)) grouped.set(permission.section, []);
    grouped.get(permission.section).push(permission);
  }
  return [...grouped.entries()].map(([name, items]) => ({ name, items }));
});

const selected = computed(() => new Set(roleForm.value.permissions));

function isEditing(role) {
  return roleForm.value.id === role.id;
}

onMounted(() => {
  loadRoles().catch(() => {});
});
</script>

<template>
  <section v-if="!mayManage" class="panel">
    <h2>{{ t("roles") }}</h2>
    <p class="muted">{{ t("rolesRequirePermission") }}</p>
  </section>

  <section v-else class="stack">
    <div class="panel">
      <div class="section-head">
        <div class="section-title">
          <KeyRound :size="15" />
          <div>
            <h2>{{ t("roles") }}</h2>
            <p class="muted">{{ t("rolesHint") }}</p>
          </div>
        </div>
        <button type="button" @click="beginEditRole(null)">
          <Plus :size="14" />
          <span>{{ t("newRole") }}</span>
        </button>
      </div>

      <div class="table settings-table">
        <div class="table-row head">
          <span>{{ t("name") }}</span>
          <span>{{ t("permissions") }}</span>
          <span>{{ t("users") }}</span>
          <span></span>
        </div>
        <div v-for="role in roles" :key="role.id" class="table-row" :class="{ active: isEditing(role) }">
          <span>
            <strong>{{ role.name }}</strong>
            <small v-if="role.builtin" class="builtin-tag"><Lock :size="11" /> {{ t("builtinRole") }}</small>
            <small v-if="role.description" class="muted">{{ role.description }}</small>
          </span>
          <span>{{ role.permissions.length }}</span>
          <span>{{ role.user_count }}</span>
          <span class="row-actions">
            <button
              v-if="!role.builtin"
              type="button"
              class="ghost"
              :disabled="isPending(`role:${role.id}`)"
              @click="beginEditRole(role)"
            >
              {{ t("edit") }}
            </button>
            <button
              v-if="!role.builtin"
              type="button"
              class="danger"
              :disabled="isPending(`role:${role.id}`)"
              @click="deleteRole(role)"
            >
              <Trash2 :size="13" />
            </button>
            <span v-else class="muted">{{ t("builtinRoleLocked") }}</span>
          </span>
        </div>
      </div>
    </div>

    <form class="panel" @submit.prevent="saveRole()">
      <div class="section-title compact">
        <KeyRound :size="14" />
        <h2>{{ roleForm.id ? t("editRole") : t("newRole") }}</h2>
      </div>
      <p class="muted">{{ t("grantHint") }}</p>

      <div class="inline-form">
        <label>{{ t("name") }}<input v-model="roleForm.name" required maxlength="64" /></label>
        <label class="wide">{{ t("description") }}<input v-model="roleForm.description" maxlength="280" /></label>
      </div>

      <div v-for="section in sections" :key="section.name" class="permission-section">
        <h3>{{ t(`permissionSection_${section.name}`) }}</h3>
        <div class="permission-grid">
          <label v-for="permission in section.items" :key="permission.key" class="permission-item">
            <input
              type="checkbox"
              :checked="selected.has(permission.key)"
              @change="toggleRolePermission(permission.key)"
            />
            <span>
              <strong>{{ permission.title }}</strong>
              <small>{{ permission.description }}</small>
              <code>{{ permission.key }}</code>
            </span>
          </label>
        </div>
      </div>

      <div class="row-actions">
        <button type="submit" :disabled="isPending(roleForm.id ? `role:${roleForm.id}` : 'role:create')">
          {{ t("save") }}
        </button>
        <button type="button" class="ghost" @click="beginEditRole(null)">{{ t("cancel") }}</button>
      </div>
    </form>
  </section>
</template>
