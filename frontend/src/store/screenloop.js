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

const canOperate = computed(() => can("tv.command"));
const isAdmin = computed(() => can("user.manage", "role.manage"));
const readyMedia = computed(() => status.value.media.filter((item) => item.status === "ready"));
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
  if (!can("role.manage")) return;
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
    deleteMedia,
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
    uploadMedia,
    uploadProgress,
    userForm,
    grantedPermissions,
    userRole,
    users,
    version,
  };
}
