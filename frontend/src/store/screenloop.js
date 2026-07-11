import { computed, ref } from "vue";
import { api, onUnauthorized, setCsrfToken } from "../api/client";
import { useI18n } from "../i18n";

const { t } = useI18n();

const session = ref(null);
const sessionExpired = ref(false);
const mySessions = ref([]);
const profilePasswordForm = ref({ current_password: "", new_password: "" });
const adminPasswordConfirm = ref("");
const status = ref({ tvs: [], media: [], playlists: [], transcode_jobs: [] });
const version = ref(null);
const tvProfiles = ref({});
const scanDevices = ref([]);
const events = ref([]);
const diagnostics = ref(null);
const users = ref([]);
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const toasts = ref([]);
const pendingActions = ref({});
const confirmState = ref(null);
let toastSeq = 0;
const liveStatus = ref({ lastStatusAt: null, lastEventsAt: null, statusError: "", eventsError: "" });
const loginForm = ref({ username: "", password: "" });
const userForm = ref({ username: "", role: "viewer", password: "" });
const passwordForms = ref({});
const uploadFile = ref(null);
const playlistForm = ref({ name: "" });
const selectedPlaylistId = ref(null);
const selectedPlaylist = ref(null);
const playlistItems = ref([]);
const selectedTvId = ref(null);
const selectedTvEvents = ref([]);
const tvForm = ref({ name: "", ip: "", profile: "generic_dlna" });
const tvEditForms = ref({});
let pollTimer = null;
let eventsPollTimer = null;
let sseConnection = null;
let sseWatchdogTimer = null;

const isAuthed = computed(() => !!session.value);
const userRole = computed(() => session.value?.user?.role || "viewer");
const canOperate = computed(() => ["admin", "operator"].includes(userRole.value));
const isAdmin = computed(() => userRole.value === "admin");
const readyMedia = computed(() => status.value.media.filter((item) => item.status === "ready"));
const failedJobs = computed(() => status.value.transcode_jobs.filter((job) => job.status === "failed"));
const runningJobs = computed(() => status.value.transcode_jobs.filter((job) => job.status === "running"));
const selectedTv = computed(() => status.value.tvs.find((tv) => tv.id === selectedTvId.value) || null);

function pushToast(kind, text) {
  const id = ++toastSeq;
  toasts.value = [...toasts.value, { id, kind, text }];
  window.setTimeout(() => dismissToast(id), kind === "error" ? 6000 : 3500);
}

function dismissToast(id) {
  toasts.value = toasts.value.filter((toast) => toast.id !== id);
}

function isPending(key) {
  return !!pendingActions.value[key];
}

async function withAction(key, action, { success = "", failure = "" } = {}) {
  if (pendingActions.value[key]) return false;
  pendingActions.value = { ...pendingActions.value, [key]: true };
  try {
    await action();
    if (success) pushToast("success", success);
    return true;
  } catch (err) {
    pushToast("error", [failure, err?.message].filter(Boolean).join(" — ") || t("userActionFailed"));
    return false;
  } finally {
    const next = { ...pendingActions.value };
    delete next[key];
    pendingActions.value = next;
  }
}

function confirmDialog(text, { danger = true } = {}) {
  return new Promise((resolve) => {
    confirmState.value = { text, danger, resolve };
  });
}

function resolveConfirm(result) {
  confirmState.value?.resolve(result);
  confirmState.value = null;
}

function applyLiveSnapshot(snapshot) {
  if (snapshot.status) {
    status.value = snapshot.status;
    liveStatus.value.lastStatusAt = new Date();
    liveStatus.value.statusError = "";
    if (selectedTvId.value && !selectedTv.value) {
      selectedTvId.value = null;
      selectedTvEvents.value = [];
    }
  }
  if (Array.isArray(snapshot.events)) {
    events.value = snapshot.events;
    liveStatus.value.lastEventsAt = new Date();
    liveStatus.value.eventsError = "";
    if (selectedTvId.value) {
      selectedTvEvents.value = snapshot.events.filter((event) => event.tv_id === selectedTvId.value).slice(0, 20);
    }
  }
}

onUnauthorized(() => {
  if (session.value) {
    sessionExpired.value = true;
  }
  session.value = null;
  setCsrfToken("");
  stopPolling();
});

async function loadSession() {
  const data = await api("/api/v1/session", { skipUnauthorizedHandler: true });
  session.value = data;
  setCsrfToken(data.csrf_token);
}

async function loadStatus() {
  status.value = await api("/api/v1/status");
  liveStatus.value.lastStatusAt = new Date();
  liveStatus.value.statusError = "";
}

async function loadTvs() {
  const data = await api("/api/v1/tvs");
  tvProfiles.value = data.profiles || {};
}

async function loadVersion() {
  version.value = await api("/api/v1/version");
}

async function loadEvents() {
  const data = await api("/api/v1/events?limit=80");
  events.value = data.events || [];
  liveStatus.value.lastEventsAt = new Date();
  liveStatus.value.eventsError = "";
}

async function loadSelectedTvEvents() {
  if (!selectedTvId.value) {
    selectedTvEvents.value = [];
    return;
  }
  const data = await api(`/api/v1/events?tv_id=${selectedTvId.value}&limit=20`);
  selectedTvEvents.value = data.events || [];
}

async function loadDiagnostics() {
  if (!isAdmin.value) return;
  diagnostics.value = await api("/api/v1/diagnostics");
}

async function loadUsers() {
  if (!isAdmin.value) return;
  const data = await api("/api/v1/users");
  users.value = data.users || [];
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadTvs(), loadVersion(), loadEvents()]);
  await loadDiagnostics().catch(() => {});
  await loadUsers().catch(() => {});
  if (selectedPlaylistId.value) {
    await loadPlaylist(selectedPlaylistId.value);
  }
  if (selectedTvId.value) {
    await loadSelectedTvEvents().catch(() => {});
  }
}

async function boot() {
  loading.value = true;
  error.value = "";
  try {
    await loadSession();
    await refreshAll();
    startPolling();
  } catch (_) {
    session.value = null;
  } finally {
    loading.value = false;
  }
}

async function login() {
  error.value = "";
  try {
    const data = await api("/api/v1/auth/login", {
      method: "POST",
      body: loginForm.value,
      skipUnauthorizedHandler: true,
    });
    session.value = data;
    sessionExpired.value = false;
    setCsrfToken(data.csrf_token);
    loginForm.value.password = "";
    await refreshAll();
    startPolling();
  } catch (_) {
    error.value = t("loginFailed");
  }
}

async function logout() {
  try {
    await api("/api/v1/auth/logout", { method: "POST", unsafe: true });
  } finally {
    session.value = null;
    setCsrfToken("");
    stopPolling();
  }
}

async function command(tv, commandName) {
  await withAction(
    `command:${tv.id}`,
    async () => {
      await api(`/api/v1/tvs/${tv.id}/commands`, {
        method: "POST",
        unsafe: true,
        body: { command: commandName },
      });
      await loadStatus();
    },
    { success: t("toastCommandQueued"), failure: t("commandFailed", { command: commandName }) },
  );
}

async function uploadMedia() {
  if (!uploadFile.value) return;
  busy.value = true;
  try {
    await withAction(
      "upload",
      async () => {
        const form = new FormData();
        form.append("file", uploadFile.value);
        await api("/api/v1/media/upload", { method: "POST", unsafe: true, body: form });
        uploadFile.value = null;
        await loadStatus();
      },
      { success: t("toastUploaded"), failure: t("uploadFailed") },
    );
  } finally {
    busy.value = false;
  }
}

function onUploadChange(event) {
  uploadFile.value = event.target.files?.[0] || null;
}

async function toggleSilent(item) {
  await withAction(`media:${item.id}`, async () => {
    await api(`/api/v1/media/${item.id}/silent`, {
      method: "POST",
      unsafe: true,
      body: { silent: !item.silent },
    });
    await loadStatus();
  });
}

async function toggleCompression(item) {
  await withAction(`media:${item.id}`, async () => {
    await api(`/api/v1/media/${item.id}/compressed`, {
      method: "POST",
      unsafe: true,
      body: { compressed: !item.compressed },
    });
    await loadStatus();
  });
}

async function deleteMedia(item) {
  if (!(await confirmDialog(t("confirmDeleteMedia", { title: item.title })))) return;
  await withAction(
    `media:${item.id}`,
    async () => {
      await api(`/api/v1/media/${item.id}`, { method: "DELETE", unsafe: true });
      await loadStatus();
    },
    { success: t("toastDeleted") },
  );
}

async function createPlaylist() {
  if (!playlistForm.value.name.trim()) return;
  await withAction("playlist:create", async () => {
    const data = await api("/api/v1/playlists", {
      method: "POST",
      unsafe: true,
      body: { name: playlistForm.value.name.trim() },
    });
    playlistForm.value.name = "";
    selectedPlaylistId.value = data.id;
    await loadStatus();
    await loadPlaylist(data.id);
  });
}

async function loadPlaylist(id) {
  if (!id) return;
  const data = await api(`/api/v1/playlists/${id}`);
  selectedPlaylistId.value = id;
  selectedPlaylist.value = data.playlist;
  playlistItems.value = data.items || [];
}

async function refreshPlaylistState() {
  await loadStatus();
  if (selectedPlaylistId.value) {
    await loadPlaylist(selectedPlaylistId.value);
  }
}

async function addPlaylistMedia(mediaId) {
  if (!selectedPlaylistId.value || !mediaId) return;
  await withAction(`playlist:${selectedPlaylistId.value}`, async () => {
    await api(`/api/v1/playlists/${selectedPlaylistId.value}/items`, {
      method: "POST",
      unsafe: true,
      body: { media_id: Number(mediaId) },
    });
    await refreshPlaylistState();
  });
}

async function movePlaylistItem(item, direction) {
  await withAction(`playlist-item:${item.id}`, async () => {
    await api(`/api/v1/playlist-items/${item.id}/move`, {
      method: "POST",
      unsafe: true,
      body: { direction },
    });
    await refreshPlaylistState();
  });
}

async function removePlaylistItem(item) {
  await withAction(`playlist-item:${item.id}`, async () => {
    await api(`/api/v1/playlist-items/${item.id}`, { method: "DELETE", unsafe: true });
    await refreshPlaylistState();
  });
}

async function deletePlaylist(playlist) {
  if (!(await confirmDialog(t("confirmDeletePlaylist", { title: playlist.name })))) return;
  await withAction(
    `playlist:${playlist.id}`,
    async () => {
      await api(`/api/v1/playlists/${playlist.id}`, { method: "DELETE", unsafe: true });
      if (selectedPlaylistId.value === playlist.id) {
        selectedPlaylistId.value = null;
        selectedPlaylist.value = null;
        playlistItems.value = [];
      }
      await loadStatus();
    },
    { success: t("toastDeleted") },
  );
}

async function createTv() {
  if (!tvForm.value.name.trim() || !tvForm.value.ip.trim()) return;
  await withAction(
    "tv:create",
    async () => {
      await api("/api/v1/tvs", {
        method: "POST",
        unsafe: true,
        body: {
          name: tvForm.value.name.trim(),
          ip: tvForm.value.ip.trim(),
          profile: tvForm.value.profile,
        },
      });
      tvForm.value = { name: "", ip: "", profile: "generic_dlna" };
      await loadStatus();
    },
    { success: t("toastSaved") },
  );
}

async function updateTvPlaylist(tv, playlistId) {
  await updateTv(tv, { playlist_id: playlistId ? Number(playlistId) : null });
}

function tvPayload(tv, patch = {}) {
  const has = (key) => Object.prototype.hasOwnProperty.call(patch, key);
  return {
    name: has("name") ? patch.name : tv.name,
    ip: has("ip") ? patch.ip : tv.ip,
    profile: has("profile") ? patch.profile : tv.profile,
    playlist_id: has("playlist_id") ? patch.playlist_id : tv.active_playlist_id ?? null,
    autoplay: has("autoplay") ? patch.autoplay : !!tv.autoplay,
    control_url: has("control_url") ? patch.control_url : tv.control_url ?? "",
  };
}

async function updateTv(tv, patch = {}) {
  return withAction(
    `tv:${tv.id}`,
    async () => {
      await api(`/api/v1/tvs/${tv.id}`, {
        method: "PATCH",
        unsafe: true,
        body: tvPayload(tv, patch),
      });
      await loadStatus();
    },
    { success: t("toastSaved") },
  );
}

function beginEditTv(tv) {
  tvEditForms.value = {
    ...tvEditForms.value,
    [tv.id]: {
      name: tv.name || "",
      ip: tv.ip || "",
      profile: tv.profile || "generic_dlna",
      playlist_id: tv.active_playlist_id || "",
      autoplay: !!tv.autoplay,
      control_url: tv.control_url || "",
    },
  };
}

function cancelEditTv(tv) {
  const next = { ...tvEditForms.value };
  delete next[tv.id];
  tvEditForms.value = next;
}

async function saveTv(tv) {
  const form = tvEditForms.value[tv.id];
  if (!form) return;
  const saved = await updateTv(tv, {
    name: form.name.trim(),
    ip: form.ip.trim(),
    profile: form.profile,
    playlist_id: form.playlist_id ? Number(form.playlist_id) : null,
    autoplay: !!form.autoplay,
    control_url: form.control_url.trim(),
  });
  if (saved) cancelEditTv(tv);
}

async function toggleTvAutoplay(tv) {
  await updateTv(tv, { autoplay: !tv.autoplay });
}

async function detectTv(tv) {
  await withAction(`tv:${tv.id}`, async () => {
    await api(`/api/v1/tvs/${tv.id}/detect`, { method: "POST", unsafe: true });
    await loadStatus();
  });
}

async function deleteTv(tv) {
  if (!(await confirmDialog(t("confirmDeleteTv", { title: tv.name })))) return;
  await withAction(
    `tv:${tv.id}`,
    async () => {
      await api(`/api/v1/tvs/${tv.id}`, { method: "DELETE", unsafe: true });
      await loadStatus();
    },
    { success: t("toastDeleted") },
  );
}

async function scanTvs() {
  await withAction("tv:scan", async () => {
    const data = await api("/api/v1/tvs/scan");
    scanDevices.value = data.devices || [];
    tvProfiles.value = data.profiles || tvProfiles.value;
  });
}

async function addScannedTv(device) {
  await withAction(
    `tv:add:${device.ip}`,
    async () => {
      await api("/api/v1/tvs", {
        method: "POST",
        unsafe: true,
        body: {
          name: device.friendly_name || device.name || device.ip,
          ip: device.ip,
          profile: device.profile || "generic_dlna",
        },
      });
      await loadStatus();
      const data = await api("/api/v1/tvs/scan");
      scanDevices.value = data.devices || [];
    },
    { success: t("toastSaved") },
  );
}

async function exportTvs() {
  const data = await api("/api/v1/tvs/export");
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `screenloop-tvs-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  window.URL.revokeObjectURL(url);
}

async function importTvsFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    await withAction(
      "tv:import",
      async () => {
        const payload = JSON.parse(await file.text());
        await api("/api/v1/tvs/import", {
          method: "POST",
          unsafe: true,
          body: payload,
        });
        await loadStatus();
      },
      { success: t("toastSaved") },
    );
  } finally {
    event.target.value = "";
  }
}

async function rebuildJob(job) {
  await withAction(`job:${job.id}`, async () => {
    await api(`/api/v1/transcode/jobs/${job.id}/rebuild`, { method: "POST", unsafe: true });
    await loadStatus();
  });
}

async function cleanupTranscode() {
  if (!(await confirmDialog(t("confirmCleanCache")))) return;
  await withAction(
    "transcode:cleanup",
    async () => {
      await api("/api/v1/transcode/cleanup", { method: "POST", unsafe: true });
      await loadStatus();
    },
    { success: t("toastDeleted") },
  );
}

async function createUser() {
  await withAction(
    "user:create",
    async () => {
      await api("/api/v1/users", {
        method: "POST",
        unsafe: true,
        body: {
          username: userForm.value.username.trim(),
          role: userForm.value.role,
          password: userForm.value.password,
        },
      });
      userForm.value = { username: "", role: "viewer", password: "" };
      await loadUsers();
    },
    { success: t("toastSaved"), failure: t("userActionFailed") },
  );
}

async function updateUser(user, patch = {}) {
  await withAction(
    `user:${user.id}`,
    async () => {
      await api(`/api/v1/users/${user.id}`, {
        method: "PATCH",
        unsafe: true,
        body: {
          role: patch.role ?? user.role,
          disabled: patch.disabled ?? !!user.disabled,
        },
      });
      await loadUsers();
    },
    { success: t("toastSaved"), failure: t("userActionFailed") },
  );
}

async function changeUserPassword(user) {
  const password = passwordForms.value[user.id] || "";
  if (!password) return;
  if (!adminPasswordConfirm.value) {
    pushToast("error", t("adminPasswordRequired"));
    return;
  }
  await withAction(
    `user:${user.id}:password`,
    async () => {
      await api(`/api/v1/users/${user.id}/password`, {
        method: "POST",
        unsafe: true,
        body: { password, admin_password: adminPasswordConfirm.value },
      });
      passwordForms.value[user.id] = "";
    },
    { success: t("toastSaved"), failure: t("userActionFailed") },
  );
}

async function changeOwnPassword() {
  const form = profilePasswordForm.value;
  if (!form.current_password || !form.new_password) return false;
  const changed = await withAction(
    "me:password",
    async () => {
      await api("/api/v1/me/password", {
        method: "POST",
        unsafe: true,
        body: { ...form },
      });
      profilePasswordForm.value = { current_password: "", new_password: "" };
      await loadMySessions().catch(() => {});
    },
    { success: t("passwordChanged"), failure: t("passwordChangeFailed") },
  );
  return changed;
}

async function loadMySessions() {
  const data = await api("/api/v1/me/sessions");
  mySessions.value = data.sessions || [];
}

async function revokeOtherSessions() {
  await withAction("me:sessions", async () => {
    await api("/api/v1/me/sessions", { method: "DELETE", unsafe: true });
    await loadMySessions();
  });
}

async function revokeSession(item) {
  await withAction(`me:session:${item.id}`, async () => {
    await api(`/api/v1/me/sessions/${item.id}`, { method: "DELETE", unsafe: true });
    await loadMySessions();
  });
}

async function selectTv(tv) {
  selectedTvId.value = tv?.id || null;
  await loadSelectedTvEvents();
}

function startPolling() {
  stopPolling();
  if (startSse()) return;
  startPollingFallback();
}

function startPollingFallback() {
  pollTimer = window.setInterval(() => {
    loadStatus().catch((err) => {
      liveStatus.value.statusError = err.message || t("liveUpdateFailed");
    });
  }, 2000);
  eventsPollTimer = window.setInterval(() => {
    loadEvents().catch((err) => {
      liveStatus.value.eventsError = err.message || t("eventsUpdateFailed");
    });
  }, 10000);
}

function startSse() {
  if (!window.EventSource) return false;
  sseConnection = new EventSource("/api/v1/stream/events", { withCredentials: true });
  sseConnection.addEventListener("snapshot", (event) => {
    try {
      applyLiveSnapshot(JSON.parse(event.data));
    } catch (err) {
      liveStatus.value.statusError = err.message || t("liveUpdateFailed");
    }
  });
  sseConnection.onerror = () => {
    liveStatus.value.statusError = t("liveUpdateError");
  };
  sseWatchdogTimer = window.setInterval(() => {
    const last = liveStatus.value.lastStatusAt?.getTime?.() || 0;
    if (last && Date.now() - last < 7000) return;
    if (sseConnection) {
      sseConnection.close();
      sseConnection = null;
    }
    if (!pollTimer) startPollingFallback();
  }, 5000);
  return true;
}

function stopPolling() {
  if (sseConnection) {
    sseConnection.close();
    sseConnection = null;
  }
  if (sseWatchdogTimer) {
    window.clearInterval(sseWatchdogTimer);
    sseWatchdogTimer = null;
  }
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  if (eventsPollTimer) {
    window.clearInterval(eventsPollTimer);
    eventsPollTimer = null;
  }
}

function statusClass(value) {
  if (["ready", "done", "PLAYING", true].includes(value)) return "ok";
  if (["failed", "ERROR", "OFFLINE", false].includes(value)) return "bad";
  return "warn";
}

export function useScreenloop() {
  return {
    addPlaylistMedia,
    addScannedTv,
    adminPasswordConfirm,
    beginEditTv,
    boot,
    busy,
    cancelEditTv,
    canOperate,
    changeOwnPassword,
    cleanupTranscode,
    command,
    confirmState,
    createPlaylist,
    createTv,
    createUser,
    changeUserPassword,
    deleteMedia,
    deletePlaylist,
    deleteTv,
    detectTv,
    diagnostics,
    error,
    events,
    exportTvs,
    failedJobs,
    importTvsFile,
    isAdmin,
    isAuthed,
    isPending,
    loadEvents,
    loadDiagnostics,
    loadUsers,
    loadPlaylist,
    liveStatus,
    loading,
    login,
    loginForm,
    logout,
    loadMySessions,
    movePlaylistItem,
    mySessions,
    onUploadChange,
    passwordForms,
    profilePasswordForm,
    playlistForm,
    playlistItems,
    readyMedia,
    rebuildJob,
    refreshAll,
    removePlaylistItem,
    resolveConfirm,
    revokeOtherSessions,
    revokeSession,
    runningJobs,
    scanDevices,
    scanTvs,
    selectedPlaylist,
    selectedPlaylistId,
    selectedTv,
    selectedTvEvents,
    selectedTvId,
    selectTv,
    session,
    sessionExpired,
    status,
    statusClass,
    stopPolling,
    toasts,
    dismissToast,
    toggleSilent,
    toggleCompression,
    toggleTvAutoplay,
    tvForm,
    tvEditForms,
    tvProfiles,
    saveTv,
    updateTv,
    updateTvPlaylist,
    updateUser,
    uploadFile,
    uploadMedia,
    userForm,
    userRole,
    users,
    version,
  };
}
