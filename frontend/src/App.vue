<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const session = ref(null);
const csrfToken = ref("");
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

async function api(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
    ...(options.unsafe ? { "X-CSRF-Token": csrfToken.value } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
    body: options.body instanceof FormData ? options.body : options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

async function loadSession() {
  const data = await api("/api/v1/session");
  session.value = data;
  csrfToken.value = data.csrf_token;
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
    csrfToken.value = data.csrf_token;
    loginForm.value.password = "";
    await refreshAll();
    startPolling();
  } catch (err) {
    error.value = "Login failed. Check username and password.";
  }
}

async function logout() {
  try {
    await api("/api/v1/auth/logout", { method: "POST", unsafe: true });
  } finally {
    session.value = null;
    csrfToken.value = "";
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
  } catch (err) {
    error.value = `Command failed: ${commandName}`;
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
  } catch (err) {
    error.value = "Upload failed. Check file size and permissions.";
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
  if (!window.confirm(`Delete media "${item.title}"?`)) return;
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
    body: { media_id: mediaId },
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
  if (!window.confirm(`Delete playlist "${playlist.name}"?`)) return;
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
  if (!window.confirm(`Delete TV "${tv.name}" and stop current playback?`)) return;
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

onMounted(boot);
onUnmounted(stopPolling);
</script>

<template>
  <main class="shell">
    <section v-if="!isAuthed" class="login-screen">
      <div class="login-card">
        <div class="brand-row">
          <div class="brand-mark" />
          <div>
            <h1>Screenloop</h1>
            <p>Corporate TV playlist control</p>
          </div>
        </div>
        <form @submit.prevent="login">
          <label>Username</label>
          <input v-model="loginForm.username" autocomplete="username" required />
          <label>Password</label>
          <input v-model="loginForm.password" type="password" autocomplete="current-password" required />
          <button type="submit">Sign in</button>
        </form>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="loading" class="muted">Checking existing session...</p>
      </div>
    </section>

    <template v-else>
      <aside class="sidebar">
        <div class="brand-row compact">
          <div class="brand-mark" />
          <div>
            <strong>Screenloop</strong>
            <span>TV operations</span>
          </div>
        </div>
        <nav>
          <button :class="{ active: activeView === 'dashboard' }" @click="activeView = 'dashboard'">Dashboard</button>
          <button :class="{ active: activeView === 'tvs' }" @click="activeView = 'tvs'">TVs</button>
          <button :class="{ active: activeView === 'media' }" @click="activeView = 'media'">Media</button>
          <button :class="{ active: activeView === 'playlists' }" @click="activeView = 'playlists'">Playlists</button>
          <button :class="{ active: activeView === 'jobs' }" @click="activeView = 'jobs'">Transcode</button>
          <button :class="{ active: activeView === 'events' }" @click="activeView = 'events'">Events</button>
          <a href="/" class="fallback">Classic UI</a>
        </nav>
        <div class="sidebar-foot">
          <span>{{ session.user.username }} / {{ session.user.role }}</span>
          <button @click="logout">Logout</button>
        </div>
      </aside>

      <section class="workspace">
        <header class="topbar">
          <div>
            <p class="eyebrow">Live control panel</p>
            <h1>{{ activeView === "dashboard" ? "TV Dashboard" : activeView }}</h1>
          </div>
          <div class="top-actions">
            <span class="pill">{{ version?.version || "dev" }}</span>
            <span v-if="version?.update_available" class="pill warn">Update {{ version.latest_version }}</span>
            <button @click="refreshAll">Refresh</button>
          </div>
        </header>

        <p v-if="error" class="error banner">{{ error }}</p>

        <section v-if="activeView === 'dashboard'" class="content-grid">
          <div class="metric ok">
            <span>Online TVs</span>
            <strong>{{ status.tvs.filter((tv) => tv.online).length }} / {{ status.tvs.length }}</strong>
          </div>
          <div class="metric">
            <span>Ready media</span>
            <strong>{{ readyMedia.length }}</strong>
          </div>
          <div class="metric warn">
            <span>Running jobs</span>
            <strong>{{ runningJobs.length }}</strong>
          </div>
          <div class="metric bad">
            <span>Failed jobs</span>
            <strong>{{ failedJobs.length }}</strong>
          </div>
        </section>

        <section v-if="activeView === 'dashboard'" class="tv-grid">
          <article v-for="tv in status.tvs" :key="tv.id" class="tv-card">
            <div class="tv-head">
              <div>
                <h2>{{ tv.name }}</h2>
                <p>{{ tv.ip }} · {{ tv.profile }}</p>
              </div>
              <span class="state" :class="statusClass(!!tv.online)">{{ tv.online ? "online" : "offline" }}</span>
            </div>
            <div class="status-row">
              <span :class="statusClass(tv.playback_state)">{{ tv.playback_state || "UNKNOWN" }}</span>
              <span :class="statusClass(!!tv.ping_reachable)">ping</span>
              <span :class="statusClass(!!tv.dlna_reachable)">dlna</span>
              <span :class="statusClass(!!tv.soap_ready)">soap</span>
            </div>
            <dl>
              <div><dt>Playlist</dt><dd>{{ tv.playlist_name || "not assigned" }}</dd></div>
              <div><dt>Now</dt><dd>{{ tv.current_media_title || "nothing started" }}</dd></div>
              <div><dt>Next</dt><dd>{{ tv.next_media_title || "playlist start" }}</dd></div>
            </dl>
            <p v-if="tv.last_error" class="error">{{ tv.last_error }}</p>
            <div v-if="canOperate" class="card-actions">
              <button @click="command(tv, 'play_next')">Play next</button>
              <button class="secondary" @click="command(tv, 'stop')">Stop</button>
              <button class="ghost" @click="command(tv, 'restart_playlist')">Restart</button>
              <button class="ghost" @click="command(tv, tv.muted ? 'unmute' : 'mute')">{{ tv.muted ? "Unmute" : "Mute" }}</button>
            </div>
          </article>
          <div v-if="!status.tvs.length" class="empty">No TVs configured yet. Open the TVs section to add or scan devices.</div>
        </section>

        <section v-if="activeView === 'tvs'" class="stack">
          <div v-if="isAdmin" class="panel">
            <div class="section-head">
              <h2>Add TV</h2>
              <button class="ghost" @click="scanTvs">Scan network</button>
            </div>
            <form class="form-grid" @submit.prevent="createTv">
              <label>Name<input v-model="tvForm.name" placeholder="Lobby Samsung" required /></label>
              <label>IP<input v-model="tvForm.ip" placeholder="192.168.1.50" required /></label>
              <label>Profile
                <select v-model="tvForm.profile">
                  <option v-for="(_, key) in tvProfiles" :key="key" :value="key">{{ key }}</option>
                </select>
              </label>
              <button type="submit">Add TV</button>
            </form>
            <div v-if="scanDevices.length" class="list scan-list">
              <article v-for="device in scanDevices" :key="device.ip" class="list-item">
                <span>
                  <strong>{{ device.friendly_name || device.ip }}</strong>
                  <small>{{ device.ip }} · {{ device.manufacturer || "unknown" }} · {{ device.model_name || "unknown" }}</small>
                </span>
                <button v-if="!device.configured" @click="addScannedTv(device)">Add</button>
                <span v-else class="pill ok">configured</span>
              </article>
            </div>
          </div>

          <div class="panel">
            <h2>Configured TVs</h2>
            <div class="table tv-table">
              <div class="table-row head"><span>Name</span><span>Status</span><span>Playlist</span><span>Actions</span></div>
              <div v-for="tv in status.tvs" :key="tv.id" class="table-row">
                <span><strong>{{ tv.name }}</strong><small>{{ tv.ip }} · {{ tv.profile }}</small></span>
                <span><b :class="statusClass(!!tv.online)">{{ tv.online ? "online" : "offline" }}</b><small>{{ tv.playback_state || "UNKNOWN" }}</small></span>
                <span>
                  <select :value="tv.active_playlist_id || ''" :disabled="!isAdmin" @change="updateTvPlaylist(tv, $event.target.value)">
                    <option value="">No playlist</option>
                    <option v-for="playlist in status.playlists" :key="playlist.id" :value="playlist.id">{{ playlist.name }}</option>
                  </select>
                </span>
                <span class="row-actions">
                  <button v-if="canOperate" @click="command(tv, 'play_next')">Play next</button>
                  <button v-if="isAdmin" class="ghost" @click="detectTv(tv)">Detect</button>
                  <button v-if="isAdmin" class="danger" @click="deleteTv(tv)">Delete</button>
                </span>
              </div>
            </div>
          </div>
        </section>

        <section v-if="activeView === 'media'" class="panel">
          <div class="section-head">
            <h2>Media library</h2>
            <form v-if="canOperate" class="upload-form" @submit.prevent="uploadMedia">
              <input type="file" accept="video/*" @change="onUploadChange" />
              <button type="submit" :disabled="busy || !uploadFile">{{ busy ? "Uploading..." : "Upload" }}</button>
            </form>
          </div>
          <div class="table media-table">
            <div class="table-row head"><span>Name</span><span>Status</span><span>Audio</span><span>Actions</span></div>
            <div v-for="item in status.media" :key="item.id" class="table-row">
              <span><strong>{{ item.title }}</strong><small>{{ item.original_name }}</small></span>
              <span><b :class="statusClass(item.status)">{{ item.status }}</b></span>
              <span>{{ item.silent ? "silent" : "original" }}</span>
              <span class="row-actions">
                <button v-if="canOperate" class="ghost" @click="toggleSilent(item)">{{ item.silent ? "Restore audio" : "Silent copy" }}</button>
                <button v-if="isAdmin" class="danger" @click="deleteMedia(item)">Delete</button>
              </span>
            </div>
          </div>
        </section>

        <section v-if="activeView === 'playlists'" class="split-panels">
          <div class="panel">
            <div class="section-head">
              <h2>Playlists</h2>
            </div>
            <form v-if="canOperate" class="inline-form" @submit.prevent="createPlaylist">
              <input v-model="playlistForm.name" placeholder="New playlist name" />
              <button type="submit">Create</button>
            </form>
            <div class="list">
              <article v-for="playlist in status.playlists" :key="playlist.id" class="list-item">
                <span><strong>{{ playlist.name }}</strong><small>{{ playlist.item_count }} items</small></span>
                <span class="row-actions">
                  <button class="ghost" @click="loadPlaylist(playlist.id)">Open</button>
                  <button v-if="isAdmin" class="danger" @click="deletePlaylist(playlist)">Delete</button>
                </span>
              </article>
            </div>
          </div>
          <div class="panel">
            <h2>{{ selectedPlaylist?.name || "Playlist items" }}</h2>
            <div v-if="selectedPlaylistId && canOperate" class="inline-form">
              <select @change="addPlaylistMedia($event.target.value); $event.target.value = ''">
                <option value="">Add ready media...</option>
                <option v-for="item in readyMedia" :key="item.id" :value="item.id">{{ item.title }}</option>
              </select>
            </div>
            <div v-if="playlistItems.length" class="list">
              <article v-for="item in playlistItems" :key="item.id" class="list-item">
                <span><strong>{{ item.title }}</strong><small>#{{ item.position }} · media {{ item.media_id }}</small></span>
                <span v-if="canOperate" class="row-actions">
                  <button class="ghost" @click="movePlaylistItem(item, 'up')">Up</button>
                  <button class="ghost" @click="movePlaylistItem(item, 'down')">Down</button>
                  <button class="danger" @click="removePlaylistItem(item)">Remove</button>
                </span>
              </article>
            </div>
            <div v-else class="empty">Open a playlist to manage its queue.</div>
          </div>
        </section>

        <section v-if="activeView === 'jobs'" class="panel">
          <div class="section-head">
            <h2>Transcode jobs</h2>
            <button v-if="isAdmin" class="ghost" @click="cleanupTranscode">Clean cache</button>
          </div>
          <div class="table">
            <div class="table-row head"><span>Media</span><span>Profile</span><span>Status</span><span>Actions</span></div>
            <div v-for="job in status.transcode_jobs" :key="job.id" class="table-row">
              <span><strong>{{ job.title }}</strong><small>{{ job.original_name }}</small></span>
              <span>{{ job.profile }}</span>
              <span><b :class="statusClass(job.status)">{{ job.status }}</b></span>
              <span class="row-actions"><button v-if="canOperate" class="ghost" @click="rebuildJob(job)">Rebuild</button></span>
            </div>
          </div>
        </section>

        <section v-if="activeView === 'events'" class="panel">
          <div class="section-head">
            <h2>Recent events</h2>
            <button class="ghost" @click="loadEvents">Refresh events</button>
          </div>
          <div class="table events-table">
            <div class="table-row head"><span>Type</span><span>Message</span><span>TV</span><span>Time</span></div>
            <div v-for="event in events" :key="event.id" class="table-row">
              <span><strong>{{ event.event_type }}</strong></span>
              <span>{{ event.message }}<small>{{ event.details }}</small></span>
              <span>{{ event.tv_name || event.tv_id || "-" }}</span>
              <span>{{ event.created_at }}</span>
            </div>
          </div>
        </section>
      </section>
    </template>
  </main>
</template>
