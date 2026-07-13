<script setup>
import { KeyRound, Power, PowerOff, RefreshCw, UserPlus } from "@lucide/vue";
import { onMounted } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatUnixTime } from "../utils/time";

const { t } = useI18n();
const {
  changeUserPassword,
  createUser,
  isAdmin,
  loadUsers,
  passwordForms,
  session,
  updateUser,
  userForm,
  users,
} = useScreenloop();

const roles = ["viewer", "operator", "admin"];

onMounted(() => {
  loadUsers().catch(() => {});
});
</script>

<template>
  <section v-if="!isAdmin" class="panel">
    <h2>{{ t("users") }}</h2>
    <p class="muted">{{ t("adminOnlyUsers") }}</p>
  </section>

  <section v-else class="stack">
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("createUser") }}</h2>
          <p class="muted">{{ t("userManagement") }}</p>
        </div>
      </div>
      <form class="form-grid" @submit.prevent="createUser">
        <label>{{ t("username") }}<input v-model="userForm.username" autocomplete="off" required /></label>
        <label>{{ t("role") }}
          <select v-model="userForm.role">
            <option v-for="role in roles" :key="role" :value="role">{{ role }}</option>
          </select>
        </label>
        <label>{{ t("password") }}<input v-model="userForm.password" type="password" autocomplete="new-password" minlength="8" required /></label>
        <button type="submit" class="action-button">
          <UserPlus :size="17" />
          <span>{{ t("create") }}</span>
        </button>
      </form>
    </div>

    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("userManagement") }}</h2>
          <p class="muted">{{ t("users") }}: {{ users.length }}</p>
        </div>
        <button class="ghost action-button" @click="loadUsers">
          <RefreshCw :size="17" />
          <span>{{ t("refresh") }}</span>
        </button>
      </div>
      <div v-if="!users.length" class="empty">{{ t("noUsers") }}</div>
      <div v-else class="table users-table">
        <div class="table-row head">
          <span>{{ t("username") }}</span>
          <span>{{ t("role") }}</span>
          <span>{{ t("status") }}</span>
          <span>{{ t("actions") }}</span>
        </div>
        <div v-for="user in users" :key="user.id" class="table-row">
          <span>
            <strong>{{ user.username }}</strong>
            <small>{{ t("createdAt") }}: {{ formatUnixTime(user.created_at) }} · {{ t("updatedAt") }}: {{ formatUnixTime(user.updated_at) }}</small>
          </span>
          <span>
            <select :value="user.role" @change="updateUser(user, { role: $event.target.value })">
              <option v-for="role in roles" :key="role" :value="role">{{ role }}</option>
            </select>
          </span>
          <span>
            <b class="status-pill" :class="user.disabled ? 'bad' : 'ok'">{{ user.disabled ? t("userDisabled") : t("enabledUser") }}</b>
          </span>
          <span class="user-actions">
            <button
              class="icon-button ghost"
              :title="user.disabled ? t('enable') : t('disable')"
              :aria-label="user.disabled ? t('enable') : t('disable')"
              :disabled="user.id === session.user.id && !user.disabled"
              @click="updateUser(user, { disabled: !user.disabled })"
            >
              <Power v-if="user.disabled" :size="18" />
              <PowerOff v-else :size="18" />
            </button>
            <form class="password-form" @submit.prevent="changeUserPassword(user)">
              <input
                v-model="passwordForms[user.id]"
                type="password"
                autocomplete="new-password"
                minlength="8"
                :placeholder="t('newPassword')"
              />
              <button type="submit" class="secondary action-button">
                <KeyRound :size="17" />
                <span>{{ t("changePassword") }}</span>
              </button>
            </form>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
