<script setup>
import { KeyRound, LogOut, RefreshCw } from "@lucide/vue";
import { onMounted, ref } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatUnixTime } from "../utils/time";

const { t } = useI18n();
const {
  changeOwnPassword,
  loadMySessions,
  mySessions,
  profilePasswordForm,
  revokeOtherSessions,
  revokeSession,
  session,
} = useScreenloop();

const passwordChanged = ref(false);

async function submitPassword() {
  passwordChanged.value = await changeOwnPassword();
}

onMounted(() => {
  loadMySessions().catch(() => {});
});
</script>

<template>
  <section class="stack">
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("myAccount") }}</h2>
          <p class="muted">{{ session.user.username }} / {{ session.user.role }}</p>
        </div>
      </div>
      <form class="form-grid" @submit.prevent="submitPassword">
        <label>{{ t("currentPassword") }}
          <input v-model="profilePasswordForm.current_password" type="password" autocomplete="current-password" required />
        </label>
        <label>{{ t("newPassword") }}
          <input v-model="profilePasswordForm.new_password" type="password" autocomplete="new-password" minlength="8" required />
        </label>
        <button type="submit" class="action-button">
          <KeyRound :size="17" />
          <span>{{ t("changePassword") }}</span>
        </button>
      </form>
      <p v-if="passwordChanged" class="muted">{{ t("passwordChanged") }}</p>
    </div>

    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("mySessions") }}</h2>
          <p class="muted">{{ t("mySessionsHint") }}</p>
        </div>
        <div class="top-actions">
          <button class="ghost action-button" @click="loadMySessions">
            <RefreshCw :size="17" />
            <span>{{ t("refresh") }}</span>
          </button>
          <button class="secondary action-button" @click="revokeOtherSessions">
            <LogOut :size="17" />
            <span>{{ t("revokeOtherSessions") }}</span>
          </button>
        </div>
      </div>
      <div v-if="!mySessions.length" class="empty">{{ t("noSessions") }}</div>
      <div v-else class="table">
        <div class="table-row head">
          <span>IP</span>
          <span>{{ t("device") }}</span>
          <span>{{ t("createdAt") }}</span>
          <span>{{ t("lastSeen") }}</span>
          <span>{{ t("actions") }}</span>
        </div>
        <div v-for="item in mySessions" :key="item.id" class="table-row">
          <span>
            {{ item.ip || "-" }}
            <b v-if="item.current" class="status-pill ok">{{ t("currentSessionBadge") }}</b>
          </span>
          <span class="muted">{{ item.user_agent || "-" }}</span>
          <span>{{ formatUnixTime(item.created_at) }}</span>
          <span>{{ formatUnixTime(item.last_seen_at) }}</span>
          <span>
            <button v-if="!item.current" class="icon-button ghost" :title="t('revokeSession')" :aria-label="t('revokeSession')" @click="revokeSession(item)">
              <LogOut :size="18" />
            </button>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
