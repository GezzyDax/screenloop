<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const session = ref(null);
const csrfToken = ref("");
const status = ref({ tvs: [], media: [], playlists: [], transcode_jobs: [] });
const version = ref(null);
const loading = ref(true);
const error = ref("");
const loginForm = ref({ username: "admin", password: "" });
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
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.unsafe ? { "X-CSRF-Token": csrfToken.value } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
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

async function loadVersion() {
  version.value = await api("/api/v1/version");
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadVersion()]);
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
          <button :class="{ active: activeView === 'media' }" @click="activeView = 'media'">Media</button>
          <button :class="{ active: activeView === 'playlists' }" @click="activeView = 'playlists'">Playlists</button>
          <button :class="{ active: activeView === 'jobs' }" @click="activeView = 'jobs'">Transcode</button>
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
          <div v-if="!status.tvs.length" class="empty">No TVs configured yet. Open Classic UI to add devices.</div>
        </section>

        <section v-if="activeView === 'media'" class="panel">
          <h2>Media library</h2>
          <div class="table">
            <div class="table-row head"><span>Name</span><span>Status</span><span>Size</span></div>
            <div v-for="item in status.media" :key="item.id" class="table-row">
              <span><strong>{{ item.title }}</strong><small>{{ item.original_name }}</small></span>
              <span><b :class="statusClass(item.status)">{{ item.status }}</b></span>
              <span>{{ item.size }}</span>
            </div>
          </div>
        </section>

        <section v-if="activeView === 'playlists'" class="panel">
          <h2>Playlists</h2>
          <div class="list">
            <article v-for="playlist in status.playlists" :key="playlist.id" class="list-item">
              <strong>{{ playlist.name }}</strong>
              <span>{{ playlist.item_count }} items</span>
            </article>
          </div>
        </section>

        <section v-if="activeView === 'jobs'" class="panel">
          <h2>Transcode jobs</h2>
          <div class="table">
            <div class="table-row head"><span>Media</span><span>Profile</span><span>Status</span><span>Attempts</span></div>
            <div v-for="job in status.transcode_jobs" :key="job.id" class="table-row">
              <span><strong>{{ job.title }}</strong><small>{{ job.original_name }}</small></span>
              <span>{{ job.profile }}</span>
              <span><b :class="statusClass(job.status)">{{ job.status }}</b></span>
              <span>{{ job.attempts }}</span>
            </div>
          </div>
        </section>
      </section>
    </template>
  </main>
</template>
