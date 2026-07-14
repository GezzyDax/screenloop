<script setup>
import { Copy, Plus, RefreshCw, Search, Trash2 } from "@lucide/vue";
import { onMounted } from "vue";
import NodeScanDialog from "../components/NodeScanDialog.vue";
import { useI18n } from "../i18n";
import { useScreenloop } from "../store/screenloop";
import { formatBytes } from "../utils/bytes";
import { formatUnixTime } from "../utils/time";

const { t } = useI18n();
const { createNode, deleteNode, isAdmin, isPending, loadNodes, newNodeEnrollToken, nodeForm, nodes, openNodeScan } = useScreenloop();

onMounted(() => {
  loadNodes().catch(() => {});
});

function copyToken() {
  navigator.clipboard?.writeText(newNodeEnrollToken.value).catch(() => {});
}
</script>

<template>
  <section v-if="!isAdmin" class="panel">
    <h2>{{ t("nodes") }}</h2>
    <p class="muted">{{ t("adminOnlyNodes") }}</p>
  </section>

  <section v-else class="stack">
    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("createNode") }}</h2>
          <p class="muted">{{ t("createNodeHint") }}</p>
        </div>
      </div>
      <form class="inline-form" @submit.prevent="createNode">
        <input v-model="nodeForm.name" :placeholder="t('nodeNamePlaceholder')" required />
        <button type="submit" class="action-button" :disabled="isPending('node:create')">
          <Plus :size="14" />
          <span>{{ t("create") }}</span>
        </button>
      </form>
      <div v-if="newNodeEnrollToken" class="enroll-token">
        <p class="muted">{{ t("enrollTokenHint") }}</p>
        <div class="enroll-token-row">
          <code>{{ newNodeEnrollToken }}</code>
          <button class="icon-button ghost" :title="t('copy')" :aria-label="t('copy')" @click="copyToken">
            <Copy :size="15" />
          </button>
        </div>
        <code class="enroll-command">sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/sl.sh && bash /tmp/sl.sh --node http://&lt;controller-ip&gt;:8099'</code>
      </div>
    </div>

    <div class="panel">
      <div class="section-head">
        <div>
          <h2>{{ t("nodes") }}</h2>
          <p class="muted">{{ t("nodes") }}: {{ nodes.length }}</p>
        </div>
        <button class="ghost action-button" @click="loadNodes">
          <RefreshCw :size="14" />
          <span>{{ t("refresh") }}</span>
        </button>
      </div>
      <div v-if="!nodes.length" class="empty">{{ t("noNodes") }}</div>
      <div v-else class="table nodes-table">
        <div class="table-row head">
          <span>{{ t("name") }}</span>
          <span>{{ t("status") }}</span>
          <span>{{ t("tvs") }}</span>
          <span>{{ t("nodeCache") }}</span>
          <span>{{ t("lastSeen") }}</span>
          <span>{{ t("actions") }}</span>
        </div>
        <div v-for="node in nodes" :key="node.id" class="table-row">
          <span>
            <strong>{{ node.name }}</strong>
            <small>{{ node.hostname || "-" }} · {{ node.version || "-" }}</small>
          </span>
          <span>
            <b v-if="!node.enrolled" class="status-pill warn">{{ t("nodeAwaitingEnrollment") }}</b>
            <b v-else class="status-pill" :class="node.connected ? 'ok' : 'bad'">
              {{ node.connected ? t("statusOnline") : t("statusOffline") }}
            </b>
          </span>
          <span>{{ node.tv_count }}</span>
          <span class="mono">{{ formatBytes(node.cache_used_bytes || 0) }}</span>
          <span>{{ formatUnixTime(node.last_seen) }}</span>
          <span class="row-actions">
            <button
              class="icon-button ghost"
              :title="node.connected ? t('scan') : t('nodeOfflineScanHint')"
              :aria-label="t('scan')"
              :disabled="!node.connected"
              @click="openNodeScan(node)"
            >
              <Search :size="15" />
            </button>
            <button class="icon-button danger" :title="t('delete')" :aria-label="t('delete')" :disabled="isPending(`node:${node.id}`)" @click="deleteNode(node)">
              <Trash2 :size="15" />
            </button>
          </span>
        </div>
      </div>
    </div>
  </section>

  <NodeScanDialog />
</template>
