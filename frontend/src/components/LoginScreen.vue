<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { error, loading, login, loginForm } = useScreenloop();
</script>

<template>
  <section class="login-screen">
    <div class="login-card">
      <div class="brand-row">
        <div class="brand-mark" />
        <div>
          <h1>Screenloop</h1>
          <p>{{ t("loginSubtitle") }}</p>
        </div>
      </div>
      <form @submit.prevent="login">
        <label>{{ t("username") }}</label>
        <input v-model="loginForm.username" autocomplete="username" required />
        <label>{{ t("password") }}</label>
        <input v-model="loginForm.password" type="password" autocomplete="current-password" required />
        <button type="submit">{{ t("signIn") }}</button>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="loading" class="muted">{{ t("sessionCheck") }}</p>
    </div>
  </section>
</template>
