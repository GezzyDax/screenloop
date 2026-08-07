<script setup>
import { KeyRound, Power, PowerOff, RefreshCw, ShieldCheck, UserPlus, X } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
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
  groups,
  loadGroups,
  loadNodes,
  nodes,
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

// A grant is a role plus where it applies, so a chip is (role, scope) and the
// same role can be held twice over different branches.
function assignmentsOf(user) {
  return (user.roles || []).map((role) => ({
    role_id: role.id,
    scope_type: role.scope_type || "global",
    scope_id: role.scope_id ?? null,
  }));
}

function scopeKey(assignment) {
  return `${assignment.role_id}:${assignment.scope_type}:${assignment.scope_id ?? ""}`;
}

function scopeLabel(role) {
  if (!role.scope_type || role.scope_type === "global") return t("scopeGlobal");
  if (role.scope_type === "group") return role.scope_group_name || t("scopeGroup");
  return role.scope_node_name || t("scopeNode");
}

function removeGrant(user, role) {
  const wanted = { role_id: role.id, scope_type: role.scope_type || "global", scope_id: role.scope_id ?? null };
  setUserRoles(user, assignmentsOf(user).filter((a) => scopeKey(a) !== scopeKey(wanted)));
}

const grantDraft = ref({});

function draftFor(userId) {
  if (!grantDraft.value[userId]) {
    grantDraft.value = { ...grantDraft.value, [userId]: { role_id: "", scope: "global" } };
  }
  return grantDraft.value[userId];
}

function addGrant(user) {
  const draft = draftFor(user.id);
  if (!draft.role_id) return;
  const [scope_type, rawId] = String(draft.scope).split(":");
  const assignment = {
    role_id: Number(draft.role_id),
    scope_type,
    scope_id: scope_type === "global" ? null : Number(rawId),
  };
  const existing = assignmentsOf(user);
  if (existing.some((a) => scopeKey(a) === scopeKey(assignment))) return;
  setUserRoles(user, [...existing, assignment]);
  grantDraft.value = { ...grantDraft.value, [user.id]: { role_id: "", scope: "global" } };
}

function isSelf(user) {
  return user.id === session.value?.user?.id;
}

onMounted(() => {
  loadUsers().catch(() => {});
  if (mayManageRoles.value) {
    loadRoles().catch(() => {});
    loadGroups().catch(() => {});
    loadNodes().catch(() => {});
  }
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
                <span v-for="role in user.roles || []" :key="scopeKey({ role_id: role.id, scope_type: role.scope_type, scope_id: role.scope_id })" class="role-chip active">
                  <span>{{ roleLabel(role) }}</span>
                  <small>{{ scopeLabel(role) }}</small>
                  <button
                    class="chip-remove"
                    :title="t('remove')"
                    :aria-label="t('remove')"
                    :disabled="isPending(`user:${user.id}`)"
                    @click="removeGrant(user, role)"
                  >
                    <X :size="11" />
                  </button>
                </span>
                <span v-if="!(user.roles || []).length" class="muted">{{ t("noRoles") }}</span>
              </div>
              <div class="grant-add">
                <select v-model="draftFor(user.id).role_id" :aria-label="t('roles')">
                  <option value="">{{ t("chooseRole") }}</option>
                  <option v-for="role in allRoles" :key="role.id" :value="role.id">{{ roleLabel(role) }}</option>
                </select>
                <select v-model="draftFor(user.id).scope" :aria-label="t('scope')">
                  <option value="global">{{ t("scopeGlobal") }}</option>
                  <option v-for="group in groups" :key="`g${group.id}`" :value="`group:${group.id}`">
                    {{ t("scopeGroup") }}: {{ group.path }}
                  </option>
                  <option v-for="node in nodes" :key="`n${node.id}`" :value="`node:${node.id}`">
                    {{ t("scopeNode") }}: {{ node.name }}
                  </option>
                </select>
                <button
                  class="ghost"
                  :disabled="!draftFor(user.id).role_id || isPending(`user:${user.id}`)"
                  @click="addGrant(user)"
                >
                  {{ t("grant") }}
                </button>
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
