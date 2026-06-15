<script setup>
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
        <h2>{{ t("createUser") }}</h2>
      </div>
      <form class="form-grid" @submit.prevent="createUser">
        <label>{{ t("username") }}<input v-model="userForm.username" autocomplete="off" required /></label>
        <label>{{ t("role") }}
          <select v-model="userForm.role">
            <option v-for="role in roles" :key="role" :value="role">{{ role }}</option>
          </select>
        </label>
        <label>{{ t("password") }}<input v-model="userForm.password" type="password" autocomplete="new-password" minlength="8" required /></label>
        <button type="submit">{{ t("create") }}</button>
      </form>
    </div>

    <div class="panel">
      <div class="section-head">
        <h2>{{ t("userManagement") }}</h2>
        <button class="ghost" @click="loadUsers">{{ t("refresh") }}</button>
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
            <b :class="user.disabled ? 'bad' : 'ok'">{{ user.disabled ? t("userDisabled") : t("enabledUser") }}</b>
          </span>
          <span class="user-actions">
            <button
              class="ghost"
              :disabled="user.id === session.user.id && !user.disabled"
              @click="updateUser(user, { disabled: !user.disabled })"
            >
              {{ user.disabled ? t("enable") : t("disable") }}
            </button>
            <form class="password-form" @submit.prevent="changeUserPassword(user)">
              <input
                v-model="passwordForms[user.id]"
                type="password"
                autocomplete="new-password"
                minlength="8"
                :placeholder="t('newPassword')"
              />
              <button type="submit" class="secondary">{{ t("changePassword") }}</button>
            </form>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
