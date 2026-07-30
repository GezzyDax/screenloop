import { ref } from "vue";

const csrfToken = ref("");
let unauthorizedHandler = null;

export function setCsrfToken(token) {
  csrfToken.value = token || "";
}

export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

export function getCsrfToken() {
  return csrfToken.value;
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
  if (response.status === 401 && !options.skipUnauthorizedHandler) {
    unauthorizedHandler?.();
  }
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.status === 204 ? null : response.json();
}

async function errorMessage(response) {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const data = JSON.parse(await response.text());
    if (typeof data.detail === "string" && data.detail) return data.detail;
    // Template validation replies with {message, errors:[...]} so the operator
    // sees which field is wrong instead of a bare status code.
    if (data.detail && typeof data.detail === "object") {
      const { message, errors } = data.detail;
      const joined = Array.isArray(errors) ? errors.join("; ") : "";
      if (message || joined) return [message, joined].filter(Boolean).join(": ");
    }
  } catch (_) {
    /* non-JSON body: never surface raw backend output to the UI */
  }
  return fallback;
}
