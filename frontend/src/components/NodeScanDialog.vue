<script setup>
import { Plus, RefreshCw, X } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";

const { t } = useI18n();
const { addScannedNodeTv, closeNodeScan, isPending, nodeScanDevices, nodeScanTarget, scanNode } = useScreenloop();

const scanning = computed(() => nodeScanTarget.value && isPending(`node:scan:${nodeScanTarget.value.id}`));

function rescan() {
  if (nodeScanTarget.value) scanNode(nodeScanTarget.value);
}
</script>

<template>
  <div v-if="nodeScanTarget" class="modal-backdrop" @click.self="closeNodeScan">
    <div class="modal modal-wide" role="dialog" aria-modal="true">
      <div class="section-head">
        <div>
          <h3>{{ t("nodeScanTitle", { name: nodeScanTarget.name }) }}</h3>
          <p>{{ t("nodeScanHint") }}</p>
        </div>
        <button class="icon-button ghost" :title="t('close')" :aria-label="t('close')" @click="closeNodeScan">
          <X :size="15" />
        </button>
      </div>

      <div v-if="scanning" class="empty">{{ t("scanning") }}</div>
      <div v-else-if="!nodeScanDevices.length" class="empty">{{ t("noScanDevices") }}</div>
      <div v-else class="list scan-list scan-modal-list">
        <article
          v-for="device in nodeScanDevices"
          :key="`${device.ip}-${device.control_url || device.location}`"
          class="list-item scan-device"
        >
          <span>
            <strong>{{ device.friendly_name || device.ip }}</strong>
            <small>{{ device.ip }} · {{ device.profile || "generic_dlna" }} · {{ device.manufacturer || t("unknown") }} · {{ device.model_name || t("unknown") }}</small>
            <small class="mono">{{ device.control_url || device.location || "-" }}</small>
          </span>
          <button v-if="!device.configured" class="action-button" :disabled="isPending(`tv:add:${device.ip}`)" @click="addScannedNodeTv(device)">
            <Plus :size="14" />
            <span>{{ t("addTv") }}</span>
          </button>
          <span v-else class="pill ok">{{ t("configured") }}</span>
        </article>
      </div>

      <div class="row-actions modal-actions">
        <button class="ghost action-button" :disabled="scanning" @click="rescan">
          <RefreshCw :size="14" />
          <span>{{ t("rescan") }}</span>
        </button>
        <button class="ghost" @click="closeNodeScan">{{ t("close") }}</button>
      </div>
    </div>
  </div>
</template>
