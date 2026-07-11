import { createRouter, createWebHistory } from "vue-router";
import DashboardView from "../views/DashboardView.vue";
import EventsView from "../views/EventsView.vue";
import MediaView from "../views/MediaView.vue";
import NodesView from "../views/NodesView.vue";
import PlaylistsView from "../views/PlaylistsView.vue";
import ProfileView from "../views/ProfileView.vue";
import SettingsView from "../views/SettingsView.vue";
import TranscodeView from "../views/TranscodeView.vue";
import TvsView from "../views/TvsView.vue";
import UsersView from "../views/UsersView.vue";

const routes = [
  { path: "/", name: "dashboard", component: DashboardView, meta: { label: "dashboard" } },
  { path: "/tvs", name: "tvs", component: TvsView, meta: { label: "tvs" } },
  { path: "/media", name: "media", component: MediaView, meta: { label: "media" } },
  { path: "/playlists", name: "playlists", component: PlaylistsView, meta: { label: "playlists" } },
  { path: "/transcode", name: "jobs", component: TranscodeView, meta: { label: "transcode" } },
  { path: "/events", name: "events", component: EventsView, meta: { label: "events" } },
  { path: "/nodes", name: "nodes", component: NodesView, meta: { label: "nodes" } },
  { path: "/users", name: "users", component: UsersView, meta: { label: "users" } },
  { path: "/profile", name: "profile", component: ProfileView, meta: { label: "profile" } },
  { path: "/settings", name: "settings", component: SettingsView, meta: { label: "settings" } },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

export const router = createRouter({
  history: createWebHistory("/"),
  routes,
});
