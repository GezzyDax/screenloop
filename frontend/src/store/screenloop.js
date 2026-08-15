import { computed, ref } from "vue";
import { api, getCsrfToken, onUnauthorized, setCsrfToken } from "../api/client.js";
import { useI18n } from "../i18n/index.js";

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
// Which zone the clip belongs to. Empty means "let the backend decide from my
// grants": a branch uploader has one zone, a central one has the whole library.
const uploadGroup = ref("");
const uploadProgress = ref(null);
const playlistForm = ref({ name: "" });
const selectedPlaylistId = ref(null);
const selectedPlaylist = ref(null);
const playlistItems = ref([]);
const selectedTvId = ref(null);
const selectedTvEvents = ref([]);
const tvForm = ref({ name: "", ip: "", profile: "generic_dlna", node_id: "", group_id: "" });
const groups = ref([]);
const schedule = ref(null);
const mediaDefaults = ref({ silent: false, compressed: false });
const editingTv = ref(null);
// The clip card: one dialog holds every property, where the clip is used, and
// the move between zones. The list itself stays read-only.
const editingMedia = ref(null);
const mediaForm = ref({ title: "", description: "", silent: false, compressed: false, group_id: "" });
const mediaUsage = ref(null);
const mediaSelection = ref([]);
const mediaZoneFilter = ref("");
// Archived clips are reachable, not shown: the library defaults to what is on
// air or waiting for approval.
const mediaStateFilter = ref("active");
const editingGroup = ref(null);
const creatingTv = ref(false);
const creatingGroup = ref(false);
const groupDraft = ref({ name: "", parent_id: "" });
const roles = ref([]);
const permissionCatalog = ref([]);
const roleForm = ref({ id: null, name: "", description: "", permissions: [] });
const scheduleForm = ref({ enabled: false, days: "0,1,2,3,4", start: "08:00", end: "20:00" });
const groupForm = ref({ name: "", parent_id: "" });
const groupScheduleForms = ref({});
const selectedGroupId = ref("");
const nodes = ref([]);
const nodeForm = ref({ name: "" });
const newNodeEnrollToken = ref("");
const nodeScanTarget = ref(null);
const nodeScanDevices = ref([]);
const templates = ref([]);
const templatesInUse = ref([]);
const templateCatalog = ref({ enabled: false, entries: [], error: null, url: "" });
const templateImportForm = ref({ url: "" });
const tvEditForms = ref({});
let pollTimer = null;
let eventsPollTimer = null;
let sseConnection = null;
let sseWatchdogTimer = null;
let sseRetryTimer = null;
let sseFailures = 0;

const isAuthed = computed(() => !!session.value);
const userRole = computed(() => session.value?.user?.role || "viewer");
const grantedPermissions = computed(() => new Set(session.value?.permissions || []));

// The panel now asks what you may do rather than what you are called. isAdmin
// and canOperate stay as the permission sets those role names carried, so the
// ten views built on them keep working while gates move one at a time.
function can(...keys) {
  const granted = grantedPermissions.value;
  return keys.length > 0 && keys.every((key) => granted.has(key));
}

const globalPermissions = computed(() => new Set(session.value?.global_permissions || []));

// A clip or playlist with no zone belongs to the whole company, and only
// somebody who holds the permission installation-wide may touch it. Asking here
// keeps the panel from offering buttons that can only answer 403.
function mayEdit(row, permission) {
  if (!can(permission)) return false;
  if (row?.group_id) return true;
  return globalPermissions.value.has(permission);
}

// role.view is global-only, so a branch-scoped grant of it would never open
// these two reads; role.manage does, at whatever scope it is held. The panel
// asks the same question the gate does.
const canReadRoles = computed(() => globalPermissions.value.has("role.view") || can("role.manage"));
const canOperate = computed(() => can("tv.command"));
const isAdmin = computed(() => can("user.manage", "role.manage"));
// What may be put into a playlist: transcoded, and not taken out of
// circulation. An archived or expired clip is kept out of the picker rather
// than silently added to a playlist that would never play it.
const readyMedia = computed(() =>
  status.value.media.filter((item) => item.status === "ready" && !["archived", "expired"].includes(mediaState(item))),
);
const failedJobs = computed(() => status.value.transcode_jobs.filter((job) => job.status === "failed"));
const runningJobs = computed(() => status.value.transcode_jobs.filter((job) => job.status === "running"));
const selectedTv = computed(() => status.value.tvs.find((tv) => tv.id === selectedTvId.value) || null);

// Selecting a branch shows everything below it, matching how permissions will
// later be inherited down the tree.
const selectedGroupSubtree = computed(() => {
  if (!selectedGroupId.value || selectedGroupId.value === "none") return null;
  const wanted = new Set([Number(selectedGroupId.value)]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const group of groups.value) {
      if (group.parent_id && wanted.has(group.parent_id) && !wanted.has(group.id)) {
        wanted.add(group.id);
        grew = true;
      }
    }
  }
  return wanted;
});

const visibleTvs = computed(() => {
  if (selectedGroupId.value === "none") return status.value.tvs.filter((tv) => !tv.group_id);
  const subtree = selectedGroupSubtree.value;
  if (!subtree) return status.value.tvs;
  return status.value.tvs.filter((tv) => tv.group_id && subtree.has(tv.group_id));
});

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

// Every destructive or publishing action gets its own worded dialog: a
// generic "are you sure" tells the operator nothing about what is about to
// happen to a screen.
function confirmDialog(text, { danger = true, title = "", confirmLabel = "" } = {}) {
  return new Promise((resolve) => {
    confirmState.value = { text, danger, title, confirmLabel, resolve };
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
  if (!can("tv.view")) {
    tvProfiles.value = {};
    return;
  }
  const data = await api("/api/v1/tvs");
  tvProfiles.value = data.profiles || {};
}

async function loadVersion() {
  version.value = await api("/api/v1/version");
}

async function loadEvents() {
  if (!can("event.view")) {
    events.value = [];
    return;
  }
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
  await Promise.all([loadStatus(), loadTvs(), loadVersion(), loadEvents(), loadGroups()]);
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
  } catch (_) {
    session.value = null;
    loading.value = false;
    return;
  }
  // Only a failed session check means "not logged in". A list that refuses to
  // load does not: somebody granted one branch has no business reading the
  // whole installation, and throwing them back to the login screen for it
  // would make a narrow role unusable.
  try {
    await refreshAll();
  } catch (_) {
    /* the individual loaders report their own trouble */
  }
  startPolling();
  loading.value = false;
}

async function login() {
  error.value = "";
  let data;
  try {
    data = await api("/api/v1/auth/login", {
      method: "POST",
      body: loginForm.value,
      skipUnauthorizedHandler: true,
    });
  } catch (_) {
    error.value = t("loginFailed");
    return;
  }
  session.value = data;
  sessionExpired.value = false;
  setCsrfToken(data.csrf_token);
  loginForm.value.password = "";
  // Same reason as in boot: the password was right, so nothing that happens
  // while filling the panel may be reported as a bad password.
  try {
    await refreshAll();
  } catch (_) {
    /* the individual loaders report their own trouble */
  }
  startPolling();
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

function uploadRequest(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/media/upload");
    xhr.setRequestHeader("X-CSRF-Token", getCsrfToken());
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        uploadProgress.value = Math.round((event.loaded / event.total) * 100);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(null);
        return;
      }
      let detail = `${xhr.status}`;
      try {
        const data = JSON.parse(xhr.responseText);
        if (typeof data.detail === "string" && data.detail) detail = data.detail;
      } catch (_) {
        /* keep status code */
      }
      reject(new Error(detail));
    };
    xhr.onerror = () => reject(new Error(t("liveUpdateError")));
    const form = new FormData();
    form.append("file", file);
    if (uploadGroup.value) form.append("group_id", String(uploadGroup.value));
    xhr.send(form);
  });
}

async function uploadMedia() {
  const file = uploadFile.value;
  if (!file) return;
  const duplicate = status.value.media.find((item) => item.original_name === file.name);
  if (duplicate && !(await confirmDialog(t("confirmDuplicateUpload", { name: file.name }), { danger: false }))) {
    return;
  }
  busy.value = true;
  uploadProgress.value = 0;
  try {
    await withAction(
      "upload",
      async () => {
        await uploadRequest(file);
        uploadFile.value = null;
        await loadStatus();
      },
      { success: t("toastUploaded"), failure: t("uploadFailed") },
    );
  } finally {
    busy.value = false;
    uploadProgress.value = null;
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

// The state of the clip itself, mirroring screenloop/lifecycle.py: an expiry
// that has passed reads as its own state, but it is a published clip that has
// simply run out.
export function mediaState(item) {
  const state = item?.lifecycle || "published";
  if (state === "published" && item?.expires_at && item.expires_at * 1000 <= Date.now()) return "expired";
  return state;
}

function mediaStateClass(state) {
  if (state === "published") return "ok";
  if (state === "draft") return "warn";
  // Out of circulation reads as quiet, not as an alarm.
  return "muted-pill";
}

function epochToLocalInput(seconds) {
  if (!seconds) return "";
  const pad = (value) => String(value).padStart(2, "0");
  const date = new Date(seconds * 1000);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function localInputToEpoch(value) {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

function openMediaCard(item) {
  editingMedia.value = item;
  mediaForm.value = {
    title: item.title || "",
    description: item.description || "",
    silent: !!item.silent,
    compressed: !!item.compressed,
    group_id: item.group_id ? String(item.group_id) : "",
    expires_at: epochToLocalInput(item.expires_at),
  };
  mediaUsage.value = null;
  loadMediaUsage(item.id).catch(() => {});
}

function closeMediaCard() {
  editingMedia.value = null;
  mediaUsage.value = null;
}

async function loadMediaUsage(mediaId) {
  mediaUsage.value = await api(`/api/v1/media/${mediaId}/usage`);
}

async function saveMediaCard() {
  const item = editingMedia.value;
  if (!item) return;
  const form = mediaForm.value;
  const zone = form.group_id ? Number(form.group_id) : null;
  await withAction(
    `media:${item.id}`,
    async () => {
      await api(`/api/v1/media/${item.id}`, {
        method: "PATCH",
        unsafe: true,
        body: {
          title: form.title.trim(),
          description: form.description.trim(),
          silent: !!form.silent,
          compressed: !!form.compressed,
          expires_at: localInputToEpoch(form.expires_at),
        },
      });
      // The zone is a separate call because moving a clip changes who can see
      // it, and that is guarded by a different permission.
      if (zone !== (item.group_id ?? null)) {
        await api(`/api/v1/media/${item.id}/owner`, { method: "PUT", unsafe: true, body: { group_id: zone } });
      }
      await loadStatus();
      closeMediaCard();
    },
    { success: t("toastSaved"), failure: t("saveFailed") },
  );
}

function toggleMediaSelection(id) {
  const next = new Set(mediaSelection.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  mediaSelection.value = [...next];
}

function clearMediaSelection() {
  mediaSelection.value = [];
}

async function bulkMoveMedia(groupId) {
  const ids = [...mediaSelection.value];
  if (!ids.length) return;
  const zone = groupId ? Number(groupId) : null;
  let moved = 0;
  let refused = 0;
  await withAction("media:bulk", async () => {
    for (const id of ids) {
      try {
        await api(`/api/v1/media/${id}/owner`, { method: "PUT", unsafe: true, body: { group_id: zone } });
        moved += 1;
      } catch (_) {
        refused += 1;
      }
    }
    await loadStatus();
    clearMediaSelection();
  });
  pushToast(refused ? "error" : "success", t("bulkMoveResult", { moved, refused }));
}

async function bulkArchiveMedia() {
  const ids = [...mediaSelection.value];
  if (!ids.length) return;
  const agreed = await confirmDialog(t("confirmBulkArchiveMedia", { count: ids.length }), {
    title: t("confirmArchiveTitle"),
    confirmLabel: t("mediaArchive"),
  });
  if (!agreed) return;
  let removed = 0;
  let refused = 0;
  await withAction("media:bulk", async () => {
    for (const id of ids) {
      try {
        await api(`/api/v1/media/${id}`, { method: "DELETE", unsafe: true });
        removed += 1;
      } catch (_) {
        refused += 1;
      }
    }
    await loadStatus();
    clearMediaSelection();
  });
  pushToast(refused ? "error" : "success", t("bulkArchiveResult", { removed, refused }));
}

// Three separate acts with three separate dialogs, because they are three
// different things: publishing puts a clip on the screens, archiving takes it
// off them, and purging deletes the file.
async function publishMedia(item) {
  const agreed = await confirmDialog(t("confirmPublishMedia", { title: item.title }), {
    danger: false,
    title: t("confirmPublishTitle"),
    confirmLabel: t("mediaPublish"),
  });
  if (!agreed) return;
  await withAction(`media:${item.id}`, async () => {
    await api(`/api/v1/media/${item.id}/publish`, { method: "POST", unsafe: true });
    await loadStatus();
    closeMediaCard();
  });
}

async function archiveMedia(item) {
  const agreed = await confirmDialog(t("confirmArchiveMedia", { title: item.title }), {
    title: t("confirmArchiveTitle"),
    confirmLabel: t("mediaArchive"),
  });
  if (!agreed) return;
  await withAction(`media:${item.id}`, async () => {
    await api(`/api/v1/media/${item.id}`, { method: "DELETE", unsafe: true });
    await loadStatus();
    closeMediaCard();
  });
}

async function purgeMedia(item) {
  const agreed = await confirmDialog(t("confirmPurgeMedia", { title: item.title }), {
    title: t("confirmPurgeTitle"),
    confirmLabel: t("mediaPurge"),
  });
  if (!agreed) return;
  await withAction(
    `media:${item.id}`,
    async () => {
      await api(`/api/v1/media/${item.id}/purge`, { method: "POST", unsafe: true });
      await loadStatus();
      closeMediaCard();
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

async function movePlaylistItemTo(itemId, position) {
  await withAction(`playlist-item:${itemId}`, async () => {
    await api(`/api/v1/playlist-items/${itemId}/position`, {
      method: "POST",
      unsafe: true,
      body: { position },
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
          node_id: tvForm.value.node_id ? Number(tvForm.value.node_id) : null,
          group_id: tvForm.value.group_id ? Number(tvForm.value.group_id) : null,
        },
      });
      tvForm.value = { name: "", ip: "", profile: "generic_dlna", node_id: "", group_id: "" };
      creatingTv.value = false;
      await loadStatus();
    },
    { success: t("toastSaved") },
  );
}

async function updateTvPlaylist(tv, playlistId) {
  await updateTv(tv, { playlist_id: playlistId ? Number(playlistId) : null });
}

export function tvPayload(tv, patch = {}) {
  const has = (key) => Object.prototype.hasOwnProperty.call(patch, key);
  return {
    name: has("name") ? patch.name : tv.name,
    ip: has("ip") ? patch.ip : tv.ip,
    profile: has("profile") ? patch.profile : tv.profile,
    playlist_id: has("playlist_id") ? patch.playlist_id : tv.active_playlist_id ?? null,
    autoplay: has("autoplay") ? patch.autoplay : !!tv.autoplay,
    control_url: has("control_url") ? patch.control_url : tv.control_url ?? "",
    node_id: has("node_id") ? patch.node_id : tv.node_id ?? null,
    group_id: has("group_id") ? patch.group_id : tv.group_id ?? null,
    schedule_mode: has("schedule_mode") ? patch.schedule_mode : tv.schedule_mode || "inherit",
    schedule_days: has("schedule_days") ? patch.schedule_days : tv.schedule_days ?? null,
    schedule_start: has("schedule_start") ? patch.schedule_start : tv.schedule_start ?? null,
    schedule_end: has("schedule_end") ? patch.schedule_end : tv.schedule_end ?? null,
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
  editingTv.value = tv;
  tvEditForms.value = {
    ...tvEditForms.value,
    [tv.id]: {
      name: tv.name || "",
      ip: tv.ip || "",
      profile: tv.profile || "generic_dlna",
      playlist_id: tv.active_playlist_id || "",
      autoplay: !!tv.autoplay,
      control_url: tv.control_url || "",
      node_id: tv.node_id || "",
      group_id: tv.group_id || "",
      schedule_mode: tv.schedule_mode || "inherit",
      schedule_days: tv.schedule_days || "0,1,2,3,4",
      schedule_start: tv.schedule_start || "08:00",
      schedule_end: tv.schedule_end || "20:00",
    },
  };
}

function cancelEditTv(tv) {
  const next = { ...tvEditForms.value };
  delete next[tv.id];
  tvEditForms.value = next;
  if (editingTv.value?.id === tv.id) editingTv.value = null;
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
    node_id: form.node_id ? Number(form.node_id) : null,
    group_id: form.group_id ? Number(form.group_id) : null,
    schedule_mode: form.schedule_mode,
    schedule_days: form.schedule_days,
    schedule_start: form.schedule_start,
    schedule_end: form.schedule_end,
  });
  if (saved) cancelEditTv(tv);
}

// --- roles -------------------------------------------------------------

async function loadRoles() {
  if (!canReadRoles.value) return;
  const [rolesData, catalog] = await Promise.all([api("/api/v1/roles"), api("/api/v1/permissions")]);
  roles.value = rolesData.roles || [];
  permissionCatalog.value = catalog.permissions || [];
}

function beginEditRole(role) {
  roleForm.value = role
    ? { id: role.id, name: role.name, description: role.description || "", permissions: [...role.permissions] }
    : { id: null, name: "", description: "", permissions: [] };
}

function toggleRolePermission(key) {
  const current = new Set(roleForm.value.permissions);
  if (current.has(key)) current.delete(key);
  else current.add(key);
  roleForm.value.permissions = [...current];
}

async function saveRole() {
  const form = roleForm.value;
  const body = { name: form.name.trim(), description: form.description.trim(), permissions: form.permissions };
  if (!body.name) return false;
  return withAction(
    form.id ? `role:${form.id}` : "role:create",
    async () => {
      if (form.id) await api(`/api/v1/roles/${form.id}`, { method: "PATCH", unsafe: true, body });
      else await api("/api/v1/roles", { method: "POST", unsafe: true, body });
      beginEditRole(null);
      await loadRoles();
    },
    { success: t("toastSaved") },
  );
}

async function deleteRole(role) {
  if (!(await confirmDialog(t("confirmDeleteRole", { name: role.name })))) return false;
  return withAction(
    `role:${role.id}`,
    async () => {
      await api(`/api/v1/roles/${role.id}`, { method: "DELETE", unsafe: true });
      await loadRoles();
    },
    { success: t("toastDeleted") },
  );
}

async function setUserRoles(user, assignments) {
  return withAction(
    `user:${user.id}`,
    async () => {
      await api(`/api/v1/users/${user.id}/roles`, { method: "PUT", unsafe: true, body: { assignments } });
      await loadUsers();
      await loadRoles();
    },
    { success: t("toastSaved") },
  );
}

// --- media defaults ----------------------------------------------------

async function loadMediaDefaults() {
  const data = await api("/api/v1/settings/media");
  mediaDefaults.value = { ...data.defaults };
}

async function saveMediaDefaults() {
  return withAction(
    "media-defaults",
    async () => {
      await api("/api/v1/settings/media", { method: "PUT", unsafe: true, body: mediaDefaults.value });
      await loadMediaDefaults();
    },
    { success: t("toastSaved") },
  );
}

// --- operating hours ---------------------------------------------------

async function loadSchedule() {
  const data = await api("/api/v1/schedule");
  schedule.value = data;
  scheduleForm.value = { ...data.schedule };
}

async function saveSchedule() {
  return withAction(
    "schedule",
    async () => {
      await api("/api/v1/schedule", { method: "PUT", unsafe: true, body: scheduleForm.value });
      await loadSchedule();
      await loadStatus();
    },
    { success: t("toastSaved") },
  );
}

async function resumeTv(tv) {
  return withAction(
    `tv:${tv.id}`,
    async () => {
      await api(`/api/v1/tvs/${tv.id}/resume`, { method: "POST", unsafe: true });
      await loadStatus();
    },
    { success: t("toastPlaybackResumed") },
  );
}

function startGroupCreate() {
  groupForm.value = { name: "", parent_id: "" };
  creatingGroup.value = true;
}

function stopGroupCreate() {
  creatingGroup.value = false;
}

function startTvCreate() {
  creatingTv.value = true;
}

function stopTvCreate() {
  creatingTv.value = false;
}

function startGroupEdit(group) {
  editingGroup.value = group;
  groupDraft.value = {
    name: group.name,
    parent_id: group.parent_id || "",
    schedule_mode: group.schedule_mode || "inherit",
    schedule_days: group.schedule_days || "0,1,2,3,4",
    schedule_start: group.schedule_start || "08:00",
    schedule_end: group.schedule_end || "20:00",
  };
}

function stopGroupEdit() {
  editingGroup.value = null;
}

async function saveGroupEdit() {
  const group = editingGroup.value;
  if (!group) return;
  const draft = groupDraft.value;
  const name = draft.name.trim();
  const parentId = draft.parent_id;
  if (!name) return;
  if (name !== group.name) await renameGroup(group, name);
  if ((parentId || null) !== (group.parent_id || null)) await moveGroup(group, parentId);
  const scheduleChanged =
    draft.schedule_mode !== (group.schedule_mode || "inherit") ||
    (draft.schedule_mode === "custom" &&
      (draft.schedule_days !== group.schedule_days ||
        draft.schedule_start !== group.schedule_start ||
        draft.schedule_end !== group.schedule_end));
  if (scheduleChanged) {
    await withAction(
      `group:${group.id}`,
      async () => {
        await api(`/api/v1/groups/${group.id}`, {
          method: "PATCH",
          unsafe: true,
          body: groupSchedulePayload(draft),
        });
        await Promise.all([loadGroups(), loadStatus()]);
      },
      { success: t("toastSaved") },
    );
  }
  editingGroup.value = null;
}

async function loadGroups() {
  if (!can("group.view")) {
    groups.value = [];
    groupScheduleForms.value = {};
    return;
  }
  const data = await api("/api/v1/groups");
  groups.value = data.groups || [];
  groupScheduleForms.value = Object.fromEntries(
    groups.value.map((group) => [
      group.id,
      {
        schedule_mode: group.schedule_mode || "inherit",
        schedule_days: group.schedule_days || "0,1,2,3,4",
        schedule_start: group.schedule_start || "08:00",
        schedule_end: group.schedule_end || "20:00",
      },
    ]),
  );
}

export function groupSchedulePayload(form) {
  const mode = form.schedule_mode || "inherit";
  return {
    schedule_mode: mode,
    schedule_days: mode === "custom" ? form.schedule_days : null,
    schedule_start: mode === "custom" ? form.schedule_start : null,
    schedule_end: mode === "custom" ? form.schedule_end : null,
  };
}

async function saveGroupSchedule(group) {
  const form = groupScheduleForms.value[group.id];
  if (!form) return false;
  return withAction(
    `group:${group.id}:schedule`,
    async () => {
      await api(`/api/v1/groups/${group.id}`, {
        method: "PATCH",
        unsafe: true,
        body: groupSchedulePayload(form),
      });
      await Promise.all([loadGroups(), loadStatus()]);
    },
    { success: t("toastSaved") },
  );
}

async function createGroup() {
  if (!groupForm.value.name.trim()) return;
  await withAction(
    "group:create",
    async () => {
      await api("/api/v1/groups", {
        method: "POST",
        unsafe: true,
        body: {
          name: groupForm.value.name.trim(),
          parent_id: groupForm.value.parent_id ? Number(groupForm.value.parent_id) : null,
        },
      });
      groupForm.value = { name: "", parent_id: "" };
      await loadGroups();
    },
    { success: t("toastSaved") },
  );
}

async function renameGroup(group, name) {
  const trimmed = (name || "").trim();
  if (!trimmed || trimmed === group.name) return;
  await withAction(
    `group:${group.id}`,
    async () => {
      await api(`/api/v1/groups/${group.id}`, { method: "PATCH", unsafe: true, body: { name: trimmed } });
      await loadGroups();
      await loadStatus();
    },
    { success: t("toastSaved") },
  );
}

async function moveGroup(group, parentId) {
  await withAction(
    `group:${group.id}`,
    async () => {
      await api(`/api/v1/groups/${group.id}`, {
        method: "PATCH",
        unsafe: true,
        body: { parent_id: parentId ? Number(parentId) : null, move: true },
      });
      await loadGroups();
    },
    { success: t("toastSaved") },
  );
}

async function deleteGroup(group) {
  if (!(await confirmDialog(t("confirmDeleteGroup", { title: group.name })))) return;
  await withAction(
    `group:${group.id}`,
    async () => {
      await api(`/api/v1/groups/${group.id}`, { method: "DELETE", unsafe: true });
      if (selectedGroupId.value === group.id) selectedGroupId.value = "";
      await loadGroups();
      await loadStatus();
    },
    { success: t("toastDeleted") },
  );
}

async function loadNodes() {
  if (!isAdmin.value) return;
  const data = await api("/api/v1/nodes");
  nodes.value = data.nodes || [];
}

async function createNode() {
  if (!nodeForm.value.name.trim()) return;
  await withAction(
    "node:create",
    async () => {
      const data = await api("/api/v1/nodes", {
        method: "POST",
        unsafe: true,
        body: { name: nodeForm.value.name.trim() },
      });
      newNodeEnrollToken.value = data.enroll_token;
      nodeForm.value.name = "";
      await loadNodes();
    },
    { success: t("toastSaved") },
  );
}

async function deleteNode(node) {
  if (!(await confirmDialog(t("confirmDeleteNode", { title: node.name })))) return;
  await withAction(
    `node:${node.id}`,
    async () => {
      await api(`/api/v1/nodes/${node.id}`, { method: "DELETE", unsafe: true });
      await loadNodes();
      await loadStatus();
    },
    { success: t("toastDeleted") },
  );
}

async function loadTemplates() {
  if (!isAdmin.value) return;
  const data = await api("/api/v1/profiles");
  templates.value = data.profiles || [];
  templatesInUse.value = data.in_use || [];
  tvProfiles.value = Object.fromEntries(templates.value.map((item) => [item.id, item]));
}

async function loadTemplateCatalog() {
  if (!isAdmin.value) return;
  templateCatalog.value = await api("/api/v1/profiles/catalog");
}

async function installTemplate(body, key) {
  return withAction(
    key,
    async () => {
      await api("/api/v1/profiles/install", { method: "POST", unsafe: true, body });
      await loadTemplates();
      if (templateCatalog.value.enabled) await loadTemplateCatalog();
    },
    { success: t("toastTemplateInstalled") },
  );
}

async function importTemplateByUrl() {
  const url = templateImportForm.value.url.trim();
  if (!url) return;
  const done = await installTemplate({ url }, "template:import");
  if (done) templateImportForm.value.url = "";
}

async function installCatalogTemplate(entry) {
  await installTemplate({ catalog_id: entry.id }, `template:${entry.id}`);
}

async function uploadTemplateFile(file) {
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  await withAction(
    "template:upload",
    async () => {
      await api("/api/v1/profiles/upload", { method: "POST", unsafe: true, body });
      await loadTemplates();
    },
    { success: t("toastTemplateInstalled") },
  );
}

async function deleteTemplate(template) {
  if (!(await confirmDialog(t("confirmDeleteTemplate", { title: template.name })))) return;
  await withAction(
    `template:${template.id}`,
    async () => {
      await api(`/api/v1/profiles/${template.id}`, { method: "DELETE", unsafe: true });
      await loadTemplates();
      if (templateCatalog.value.enabled) await loadTemplateCatalog();
    },
    { success: t("toastDeleted") },
  );
}

function openNodeScan(node) {
  nodeScanTarget.value = node;
  nodeScanDevices.value = [];
  scanNode(node);
}

function closeNodeScan() {
  nodeScanTarget.value = null;
  nodeScanDevices.value = [];
}

async function scanNode(node) {
  await withAction(`node:scan:${node.id}`, async () => {
    const data = await api(`/api/v1/nodes/${node.id}/scan`, { method: "POST", unsafe: true });
    nodeScanDevices.value = data.devices || [];
    tvProfiles.value = data.profiles || tvProfiles.value;
  });
}

async function addScannedNodeTv(device) {
  const node = nodeScanTarget.value;
  if (!node) return;
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
          node_id: node.id,
        },
      });
      await loadStatus();
      await scanNode(node);
    },
    { success: t("toastSaved") },
  );
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
  sseFailures = 0;
  if (startSse()) return;
  startPollingFallback();
}

function startPollingFallback() {
  if (pollTimer) return;
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

function stopPollingFallback() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  if (eventsPollTimer) {
    window.clearInterval(eventsPollTimer);
    eventsPollTimer = null;
  }
}

function startSse() {
  if (!window.EventSource) return false;
  sseConnection = new EventSource("/api/v1/stream/events", { withCredentials: true });
  sseConnection.addEventListener("snapshot", (event) => {
    try {
      applyLiveSnapshot(JSON.parse(event.data));
      sseFailures = 0;
      // SSE recovered: fall back off the polling downgrade.
      stopPollingFallback();
    } catch (err) {
      liveStatus.value.statusError = err.message || t("liveUpdateFailed");
    }
  });
  sseConnection.onerror = () => {
    liveStatus.value.statusError = t("liveUpdateError");
    scheduleSseRetry();
  };
  sseWatchdogTimer = window.setInterval(() => {
    const last = liveStatus.value.lastStatusAt?.getTime?.() || 0;
    if (last && Date.now() - last < 7000) return;
    scheduleSseRetry();
  }, 5000);
  return true;
}

function closeSse() {
  if (sseConnection) {
    sseConnection.close();
    sseConnection = null;
  }
  if (sseWatchdogTimer) {
    window.clearInterval(sseWatchdogTimer);
    sseWatchdogTimer = null;
  }
}

function scheduleSseRetry() {
  closeSse();
  if (!session.value) return;
  startPollingFallback();
  if (sseRetryTimer) return;
  sseFailures += 1;
  const delay = Math.min(30000, 2000 * 2 ** Math.min(sseFailures, 4));
  sseRetryTimer = window.setTimeout(() => {
    sseRetryTimer = null;
    if (session.value && !sseConnection) startSse();
  }, delay);
}

function stopPolling() {
  closeSse();
  stopPollingFallback();
  if (sseRetryTimer) {
    window.clearTimeout(sseRetryTimer);
    sseRetryTimer = null;
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
    addScannedNodeTv,
    addScannedTv,
    adminPasswordConfirm,
    beginEditTv,
    boot,
    busy,
    cancelEditTv,
    can,
    canOperate,
    changeOwnPassword,
    cleanupTranscode,
    closeNodeScan,
    command,
    confirmState,
    createGroup,
    createNode,
    createPlaylist,
    createTv,
    createUser,
    changeUserPassword,
    deleteGroup,
    deleteNode,
    deleteTemplate,
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
    importTemplateByUrl,
    installCatalogTemplate,
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
    loadGroups,
    loadNodes,
    loadTemplateCatalog,
    loadTemplates,
    movePlaylistItem,
    movePlaylistItemTo,
    mySessions,
    newNodeEnrollToken,
    groupForm,
    groupScheduleForms,
    groups,
    moveGroup,
    nodeForm,
    nodeScanDevices,
    nodeScanTarget,
    nodes,
    onUploadChange,
    openNodeScan,
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
    scanNode,
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
    pushToast,
    toggleSilent,
    toggleCompression,
    toggleTvAutoplay,
    tvForm,
    tvEditForms,
    templateCatalog,
    templateImportForm,
    templates,
    templatesInUse,
    renameGroup,
    selectedGroupId,
    tvProfiles,
    visibleTvs,
    uploadTemplateFile,
    saveTv,
    saveGroupSchedule,
    schedule,
    scheduleForm,
    loadSchedule,
    loadMediaDefaults,
    saveMediaDefaults,
    mediaDefaults,
    editingTv,
    editingGroup,
    creatingTv,
    creatingGroup,
    startTvCreate,
    stopTvCreate,
    startGroupCreate,
    stopGroupCreate,
    groupDraft,
    startGroupEdit,
    stopGroupEdit,
    saveGroupEdit,
    canReadRoles,
    loadRoles,
    roles,
    roleForm,
    permissionCatalog,
    beginEditRole,
    toggleRolePermission,
    saveRole,
    deleteRole,
    setUserRoles,
    saveSchedule,
    resumeTv,
    updateTv,
    updateTvPlaylist,
    updateUser,
    uploadFile,
    archiveMedia,
    bulkArchiveMedia,
    bulkMoveMedia,
    clearMediaSelection,
    closeMediaCard,
    editingMedia,
    mayEdit,
    mediaForm,
    mediaSelection,
    mediaState,
    mediaStateClass,
    mediaStateFilter,
    mediaUsage,
    mediaZoneFilter,
    openMediaCard,
    publishMedia,
    purgeMedia,
    saveMediaCard,
    toggleMediaSelection,
    uploadGroup,
    uploadMedia,
    uploadProgress,
    userForm,
    grantedPermissions,
    userRole,
    users,
    version,
  };
}
