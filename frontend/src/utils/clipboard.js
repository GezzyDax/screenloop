export async function copyText(
  text,
  environment = { navigator: globalThis.navigator, document: globalThis.document },
) {
  try {
    if (environment.navigator?.clipboard?.writeText) {
      await environment.navigator.clipboard.writeText(text);
      return;
    }
  } catch (_) {
    // Browser policy may reject Clipboard API access on a plain HTTP LAN origin.
  }

  const documentRef = environment.document;
  if (!documentRef?.body || typeof documentRef.execCommand !== "function") {
    throw new Error("Unable to copy text");
  }

  const textarea = documentRef.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  documentRef.body.appendChild(textarea);
  try {
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    if (!documentRef.execCommand("copy")) {
      throw new Error("Unable to copy text");
    }
  } finally {
    textarea.remove();
  }
}
