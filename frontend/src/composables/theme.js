import { ref } from "vue";

const STORAGE_KEY = "screenloop.theme";
const media = window.matchMedia("(prefers-color-scheme: dark)");
const theme = ref(localStorage.getItem(STORAGE_KEY) || "auto");

function resolvedTheme() {
  if (theme.value === "auto") return media.matches ? "dark" : "light";
  return theme.value;
}

function applyTheme() {
  document.documentElement.dataset.theme = resolvedTheme();
}

media.addEventListener("change", applyTheme);
applyTheme();

function toggleTheme() {
  theme.value = resolvedTheme() === "dark" ? "light" : "dark";
  localStorage.setItem(STORAGE_KEY, theme.value);
  applyTheme();
}

export function useTheme() {
  return { theme, resolvedTheme, toggleTheme };
}
