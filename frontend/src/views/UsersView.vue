<script setup>
import { KeyRound, Power, PowerOff, RefreshCw, ShieldCheck, UserPlus } from "@lucide/vue";
import { computed, onMounted } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatUnixTime } from "../utils/time";

const { t, tOr } = useI18n();
const {
  adminPasswordConfirm,
  can,
  changeUserPassword,
  createUser,
  isAdmin,
  isPending,
  loadRoles,
  loadUsers,
  passwordForms,
  roles: allRoles,
  session,
  setUserRoles,
  updateUser,
  userForm,
  users,
} = useScreenloop();

const builtinRoles = ["viewer", "operator", "admin"];

// Authority is the union of the roles a user holds, and the three built-in
// roles are rows in that same table. A separate "role" dropdown would be a
// second control for the same thing, so the chips are the only one -- the
// backend keeps `users.role` in step by deriving it from the grants.
const mayManageRoles = computed(() => can("role.manage"));

function roleLabel(role) {
  return role.builtin ? tOr(`roleName_${role.name}`, role.name) : role.name;
}

function builtinLabel(name) {
  return tOr(`roleName_${name}`, name);
}

function heldRoleIds(user) {
  return (user.roles || []).map((role) => role.id);
}

function toggleRole(user, roleId) {
  const held = new Set(heldRoleIds(user));
  if (held.has(roleId)) held.delete(roleId);
  else held.add(roleId);
  setUserRoles(user, [...held]);
}

function isSelf(user) {
  return user.id === session.value?.user?.id;
}

onMounted(() => {
  loadUsers().catch(() => {});
  if (mayManageRoles.value) loadRoles().catch(() => {});
});
</script>

<template>
  <section v-if="!isAdmin" class="panel">
    <h2>{{ t("users") }}</h2>
    <p class="muted">{{ t("adminOnlyUsers") }}</p>
  </section>

  <section v-else class="stack">
    <div class="panel">
      <div class="section-title">
        <UserPlus :size="15" />
        <div>
          <h2>{{ t("createUser") }}</h2>
          <p class="muted">{{ t("userManagement") }}</p>
        </div>
      </div>
      <form class="form-grid" @submit.prevent="createUser">
        <label>{{ t("username") }}<input v-model="userForm.username" autocomplete="off" required /></label>
        <label>{{ t("role") }}
          <select v-model="userForm.role">
            <option v-for="role in builtinRoles" :key="role" :value="role">{{ builtinLabel(role) }}</option>
          </select>
        </label>
        <label>{{ t("password") }}<input v-model="userForm.password" type="password" autocomplete="new-password" minlength="8" required /></label>
        <button type="submit" class="action-button">
          <UserPlus :size="14" />
          <span>{{ t("create") }}</span>
        </button>
      </form>
    </div>

    <div class="panel">
      <div class="section-head">
        <div class="section-title">
          <ShieldCheck :size="15" />
          <div>
            <h2>{{ t("userManagement") }}</h2>
            <p class="muted">{{ t("users") }}: {{ users.length }}</p>
          </div>
        </div>
        <button class="ghost action-button" @click="loadUsers">
          <RefreshCw :size="14" />
          <span>{{ t("refresh") }}</span>
        </button>
      </div>

      <label class="admin-password-confirm">
        {{ t("adminPasswordConfirmLabel") }}
        <input v-model="adminPasswordConfirm" type="password" autocomplete="current-password" />
        <small>{{ t("adminPasswordHint") }}</small>
      </label>

      <div v-if="!users.length" class="empty">{{ t("noUsers") }}</div>
      <div v-else class="user-list">
        <article v-for="user in users" :key="user.id" class="user-item" :class="{ off: user.disabled }">
          <header>
            <div class="user-identity">
              <strong>{{ user.username }}</strong>
              <span v-if="isSelf(user)" class="badge">{{ t("you") }}</span>
              <b class="status-pill" :class="user.disabled ? 'bad' : 'ok'">
                {{ user.disabled ? t("userDisabled") : t("enabledUser") }}
              </b>
            </div>
            <div class="user-item-actions">
              <span class="muted" :title="`${t('createdAt')}: ${formatUnixTime(user.created_at)}`">
                {{ t("updatedAt") }}: {{ formatUnixTime(user.updated_at) }}
              </span>
              <button
                class="icon-button ghost"
                :title="user.disabled ? t('enable') : t('disable')"
                :aria-label="user.disabled ? t('enable') : t('disable')"
                :disabled="isSelf(user) && !user.disabled"
                @click="updateUser(user, { disabled: !user.disabled })"
              >
                <Power v-if="user.disabled" :size="15" />
                <PowerOff v-else :size="15" />
              </button>
            </div>
          </header>

          <div class="user-item-body">
            <div v-if="mayManageRoles" class="user-roles">
              <span class="field-label"><KeyRound :size="12" />{{ t("assignedRoles") }}</span>
              <div class="role-chips">
                <label
                  v-for="role in allRoles"
                  :key="role.id"
                  class="role-chip"
                  :class="{ active: heldRoleIds(user).includes(role.id) }"
                  :title="role.description"
                >
                  <input
                    type="checkbox"
                    :checked="heldRoleIds(user).includes(role.id)"
                    :disabled="isPending(`user:${user.id}`)"
                    @change="toggleRole(user, role.id)"
                  />
                  <span>{{ roleLabel(role) }}</span>
                </label>
              </div>
              <small class="muted">{{ t("permissionsHeld", { count: (user.permissions || []).length }) }}</small>
            </div>

            <form class="password-form" @submit.prevent="changeUserPassword(user)">
              <span class="field-label">{{ t("newPassword") }}</span>
              <div class="password-row">
                <input
                  v-model="passwordForms[user.id]"
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                  :placeholder="t('newPassword')"
                />
                <button type="submit" class="ghost">{{ t("changePassword") }}</button>
              </div>
            </form>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>
