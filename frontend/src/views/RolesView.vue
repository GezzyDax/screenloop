<script setup>
import { KeyRound, Lock, Plus, Trash2, Users } from "@lucide/vue";
import { computed, onMounted } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t, tOr } = useI18n();
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

function permissionKey(key, suffix = "") {
  return `perm_${key.replaceAll(".", "_")}${suffix}`;
}

// The catalogue arrives flat and already ordered; grouping here keeps the
// backend's ordering rather than inventing a second one. Titles fall back to
// the English the API sent when a translation is missing.
const sections = computed(() => {
  const grouped = new Map();
  for (const permission of permissionCatalog.value) {
    if (!grouped.has(permission.section)) grouped.set(permission.section, []);
    grouped.get(permission.section).push({
      ...permission,
      label: tOr(permissionKey(permission.key), permission.title),
      hint: tOr(permissionKey(permission.key, "_desc"), permission.description),
    });
  }
  return [...grouped.entries()].map(([name, items]) => ({ name, items }));
});

const selected = computed(() => new Set(roleForm.value.permissions));
const editing = computed(() => roleForm.value.id !== null);

function roleLabel(role) {
  return role.builtin ? tOr(`roleName_${role.name}`, role.name) : role.name;
}

function roleDescription(role) {
  return role.builtin ? tOr(`builtinRoleHint_${role.name}`, role.description) : role.description;
}

function sectionState(section) {
  const chosen = section.items.filter((item) => selected.value.has(item.key)).length;
  return { chosen, total: section.items.length, all: chosen === section.items.length };
}

function toggleSection(section) {
  const { all } = sectionState(section);
  for (const item of section.items) {
    if (selected.value.has(item.key) === all) toggleRolePermission(item.key);
  }
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

      <div class="role-list">
        <article
          v-for="role in roles"
          :key="role.id"
          class="role-item"
          :class="{ active: roleForm.id === role.id }"
        >
          <div class="role-item-main">
            <div class="role-item-name">
              <strong>{{ roleLabel(role) }}</strong>
              <span v-if="role.builtin" class="badge" :title="t('builtinRoleLocked')">
                <Lock :size="10" />{{ t("builtinRole") }}
              </span>
            </div>
            <p v-if="roleDescription(role)" class="muted">{{ roleDescription(role) }}</p>
          </div>
          <div class="role-item-meta">
            <span :title="t('permissions')"><KeyRound :size="12" />{{ role.permissions.length }}</span>
            <span :title="t('users')"><Users :size="12" />{{ role.user_count }}</span>
          </div>
          <div class="role-item-actions">
            <template v-if="!role.builtin">
              <button type="button" class="ghost" :disabled="isPending(`role:${role.id}`)" @click="beginEditRole(role)">
                {{ t("edit") }}
              </button>
              <button
                type="button"
                class="icon-button ghost"
                :title="t('delete')"
                :aria-label="t('delete')"
                :disabled="isPending(`role:${role.id}`)"
                @click="deleteRole(role)"
              >
                <Trash2 :size="14" />
              </button>
            </template>
          </div>
        </article>
      </div>
    </div>

    <form class="panel" @submit.prevent="saveRole()">
      <div class="section-head">
        <div class="section-title">
          <KeyRound :size="15" />
          <div>
            <h2>{{ editing ? t("editRole") : t("newRole") }}</h2>
            <p class="muted">{{ t("grantHint") }}</p>
          </div>
        </div>
        <strong class="muted">{{ t("selectedCount", { count: roleForm.permissions.length }) }}</strong>
      </div>

      <div class="role-fields">
        <label>{{ t("name") }}<input v-model="roleForm.name" required maxlength="64" /></label>
        <label>{{ t("description") }}<input v-model="roleForm.description" maxlength="280" /></label>
      </div>

      <div class="permission-columns">
        <section v-for="section in sections" :key="section.name" class="permission-block">
          <header>
            <h3>{{ t(`permissionSection_${section.name}`) }}</h3>
            <button type="button" class="link" @click="toggleSection(section)">
              {{ sectionState(section).all ? t("clearAll") : t("selectAll") }}
            </button>
          </header>
          <label
            v-for="permission in section.items"
            :key="permission.key"
            class="permission-row"
            :class="{ on: selected.has(permission.key) }"
            :title="`${permission.hint}\n${permission.key}`"
          >
            <input
              type="checkbox"
              :checked="selected.has(permission.key)"
              @change="toggleRolePermission(permission.key)"
            />
            <span>{{ permission.label }}</span>
          </label>
        </section>
      </div>

      <div class="row-actions">
        <button type="submit" :disabled="isPending(editing ? `role:${roleForm.id}` : 'role:create')">
          {{ t("save") }}
        </button>
        <button type="button" class="ghost" @click="beginEditRole(null)">{{ t("cancel") }}</button>
      </div>
    </form>
  </section>
</template>
