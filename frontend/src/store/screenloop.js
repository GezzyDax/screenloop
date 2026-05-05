import { computed, ref } from "vue";
import { api, setCsrfToken } from "../api/client";
import { useI18n } from "../i18n";

const { t } = useI18n();

const session = ref(null);
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
const liveStatus = ref({ lastStatusAt: null, lastEventsAt: null, statusError: "", eventsError: "" });
const loginForm = ref({ username: "admin", password: "" });
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
const activeView = ref("dashboard");
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

async function loadSession() {
  const data = await api("/api/v1/session");
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
    });
    session.value = data;
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
  error.value = "";
  try {
    await api(`/api/v1/tvs/${tv.id}/commands`, {
      method: "POST",
      unsafe: true,
      body: { command: commandName },
    });
    await loadStatus();
  } catch (_) {
    error.value = t("commandFailed", { command: commandName });
  }
}

async function uploadMedia() {
  if (!uploadFile.value) return;
  error.value = "";
  busy.value = true;
  try {
    const form = new FormData();
    form.append("file", uploadFile.value);
    await api("/api/v1/media/upload", { method: "POST", unsafe: true, body: form });
    uploadFile.value = null;
    await refreshAll();
  } catch (_) {
    error.value = t("uploadFailed");
  } finally {
    busy.value = false;
  }
}

function onUploadChange(event) {
  uploadFile.value = event.target.files?.[0] || null;
}

async function toggleSilent(item) {
  await api(`/api/v1/media/${item.id}/silent`, {
    method: "POST",
    unsafe: true,
    body: { silent: !item.silent },
  });
  await refreshAll();
}

async function toggleCompression(item) {
  await api(`/api/v1/media/${item.id}/compressed`, {
    method: "POST",
    unsafe: true,
    body: { compressed: !item.compressed },
  });
  await refreshAll();
}

async function deleteMedia(item) {
  if (!window.confirm(t("confirmDeleteMedia", { title: item.title }))) return;
  await api(`/api/v1/media/${item.id}`, { method: "DELETE", unsafe: true });
  await refreshAll();
}

async function createPlaylist() {
  if (!playlistForm.value.name.trim()) return;
  const data = await api("/api/v1/playlists", {
    method: "POST",
    unsafe: true,
    body: { name: playlistForm.value.name.trim() },
  });
  playlistForm.value.name = "";
  selectedPlaylistId.value = data.id;
  await refreshAll();
}

async function loadPlaylist(id) {
  if (!id) return;
  const data = await api(`/api/v1/playlists/${id}`);
  selectedPlaylistId.value = id;
  selectedPlaylist.value = data.playlist;
  playlistItems.value = data.items || [];
}

async function addPlaylistMedia(mediaId) {
  if (!selectedPlaylistId.value || !mediaId) return;
  await api(`/api/v1/playlists/${selectedPlaylistId.value}/items`, {
    method: "POST",
    unsafe: true,
    body: { media_id: Number(mediaId) },
  });
  await refreshAll();
}

async function movePlaylistItem(item, direction) {
  await api(`/api/v1/playlist-items/${item.id}/move`, {
    method: "POST",
    unsafe: true,
    body: { direction },
  });
  await refreshAll();
}

async function removePlaylistItem(item) {
  await api(`/api/v1/playlist-items/${item.id}`, { method: "DELETE", unsafe: true });
  await refreshAll();
}

async function deletePlaylist(playlist) {
  if (!window.confirm(t("confirmDeletePlaylist", { title: playlist.name }))) return;
  await api(`/api/v1/playlists/${playlist.id}`, { method: "DELETE", unsafe: true });
  if (selectedPlaylistId.value === playlist.id) {
    selectedPlaylistId.value = null;
    selectedPlaylist.value = null;
    playlistItems.value = [];
  }
  await refreshAll();
}

async function createTv() {
  if (!tvForm.value.name.trim() || !tvForm.value.ip.trim()) return;
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
  await refreshAll();
}

async function updateTvPlaylist(tv, playlistId) {
  await api(`/api/v1/tvs/${tv.id}`, {
    method: "PATCH",
    unsafe: true,
    body: {
      name: tv.name,
      ip: tv.ip,
      profile: tv.profile,
      playlist_id: playlistId ? Number(playlistId) : null,
      autoplay: !!tv.autoplay,
      control_url: tv.control_url || "",
    },
  });
  await refreshAll();
}

async function detectTv(tv) {
  await api(`/api/v1/tvs/${tv.id}/detect`, { method: "POST", unsafe: true });
  await refreshAll();
}

async function deleteTv(tv) {
  if (!window.confirm(t("confirmDeleteTv", { title: tv.name }))) return;
  await api(`/api/v1/tvs/${tv.id}`, { method: "DELETE", unsafe: true });
  await refreshAll();
}

async function scanTvs() {
  const data = await api("/api/v1/tvs/scan");
  scanDevices.value = data.devices || [];
  tvProfiles.value = data.profiles || tvProfiles.value;
}

async function addScannedTv(device) {
  await api("/api/v1/tvs", {
    method: "POST",
    unsafe: true,
    body: {
      name: device.friendly_name || device.name || device.ip,
      ip: device.ip,
      profile: device.profile || "generic_dlna",
    },
  });
  await refreshAll();
  await scanTvs();
}

async function rebuildJob(job) {
  await api(`/api/v1/transcode/jobs/${job.id}/rebuild`, { method: "POST", unsafe: true });
  await refreshAll();
}

async function cleanupTranscode() {
  await api("/api/v1/transcode/cleanup", { method: "POST", unsafe: true });
  await refreshAll();
}

async function createUser() {
  error.value = "";
  try {
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
  } catch (err) {
    error.value = err.message || t("userActionFailed");
  }
}

async function updateUser(user, patch = {}) {
  error.value = "";
  try {
    await api(`/api/v1/users/${user.id}`, {
      method: "PATCH",
      unsafe: true,
      body: {
        role: patch.role ?? user.role,
        disabled: patch.disabled ?? !!user.disabled,
      },
    });
    await loadUsers();
  } catch (err) {
    error.value = err.message || t("userActionFailed");
  }
}

async function changeUserPassword(user) {
  const password = passwordForms.value[user.id] || "";
  if (!password) return;
  error.value = "";
  try {
    await api(`/api/v1/users/${user.id}/password`, {
      method: "POST",
      unsafe: true,
      body: { password },
    });
    passwordForms.value[user.id] = "";
  } catch (err) {
    error.value = err.message || t("userActionFailed");
  }
}

function setActiveView(view) {
  activeView.value = view;
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
    activeView,
    addPlaylistMedia,
    addScannedTv,
    boot,
    busy,
    canOperate,
    cleanupTranscode,
    command,
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
    failedJobs,
    isAdmin,
    isAuthed,
    loadEvents,
    loadDiagnostics,
    loadUsers,
    loadPlaylist,
    liveStatus,
    loading,
    login,
    loginForm,
    logout,
    movePlaylistItem,
    onUploadChange,
    passwordForms,
    playlistForm,
    playlistItems,
    readyMedia,
    rebuildJob,
    refreshAll,
    removePlaylistItem,
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
    setActiveView,
    status,
    statusClass,
    stopPolling,
    toggleSilent,
    toggleCompression,
    tvForm,
    tvProfiles,
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
