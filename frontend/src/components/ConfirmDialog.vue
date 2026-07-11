<script setup>
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { confirmState, resolveConfirm } = useScreenloop();
</script>

<template>
  <div v-if="confirmState" class="modal-backdrop" @click.self="resolveConfirm(false)">
    <div class="modal" role="dialog" aria-modal="true">
      <h3>{{ t("confirmTitle") }}</h3>
      <p>{{ confirmState.text }}</p>
      <div class="row-actions modal-actions">
        <button :class="confirmState.danger ? 'danger' : ''" @click="resolveConfirm(true)">{{ t("confirmYes") }}</button>
        <button class="ghost" @click="resolveConfirm(false)">{{ t("cancel") }}</button>
      </div>
    </div>
  </div>
</template>
