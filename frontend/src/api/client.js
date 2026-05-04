import { ref } from "vue";

const csrfToken = ref("");

export function setCsrfToken(token) {
  csrfToken.value = token || "";
}

export async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const headers = {
    Accept: "application/json",
    ...(options.body && !isForm ? { "Content-Type": "application/json" } : {}),
    ...(options.unsafe ? { "X-CSRF-Token": csrfToken.value } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
    body: isForm ? options.body : options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}
