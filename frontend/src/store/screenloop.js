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
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const loginForm = ref({ username: "admin", password: "" });
const uploadFile = ref(null);
const playlistForm = ref({ name: "" });
const selectedPlaylistId = ref(null);
const selectedPlaylist = ref(null);
const playlistItems = ref([]);
const tvForm = ref({ name: "", ip: "", profile: "generic_dlna" });
const activeView = ref("dashboard");
let pollTimer = null;

const isAuthed = computed(() => !!session.value);
const userRole = computed(() => session.value?.user?.role || "viewer");
const canOperate = computed(() => ["admin", "operator"].includes(userRole.value));
const isAdmin = computed(() => userRole.value === "admin");
const readyMedia = computed(() => status.value.media.filter((item) => item.status === "ready"));
const failedJobs = computed(() => status.value.transcode_jobs.filter((job) => job.status === "failed"));
const runningJobs = computed(() => status.value.transcode_jobs.filter((job) => job.status === "running"));

async function loadSession() {
  const data = await api("/api/v1/session");
  session.value = data;
  setCsrfToken(data.csrf_token);
}

async function loadStatus() {
  status.value = await api("/api/v1/status");
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
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadTvs(), loadVersion(), loadEvents()]);
  if (selectedPlaylistId.value) {
    await loadPlaylist(selectedPlaylistId.value);
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

function setActiveView(view) {
  activeView.value = view;
}

function startPolling() {
  stopPolling();
  pollTimer = window.setInterval(() => {
    loadStatus().catch(() => {});
  }, 4000);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
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
    deleteMedia,
    deletePlaylist,
    deleteTv,
    detectTv,
    error,
    events,
    failedJobs,
    isAdmin,
    isAuthed,
    loadEvents,
    loadPlaylist,
    loading,
    login,
    loginForm,
    logout,
    movePlaylistItem,
    onUploadChange,
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
    session,
    setActiveView,
    status,
    statusClass,
    stopPolling,
    toggleSilent,
    tvForm,
    tvProfiles,
    updateTvPlaylist,
    uploadFile,
    uploadMedia,
    userRole,
    version,
  };
}
