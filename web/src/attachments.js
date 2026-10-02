import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";

export const attachmentLabel = name => name.includes(".file.") ? name.slice(name.indexOf(".file.") + 6) : "Image";
export const isImage = name => /^[a-f0-9]{64}\.(png|jpg|gif|webp)$/.test(name);
const MAX_FILES = 10;
const MAX_BYTES = 10 * 1024 * 1024;
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");

export function useAttachments(files, setFiles, setStatus, scope) {
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const session = useRef(null);
  const filesRef = useRef(files);
  filesRef.current = files;
  useEffect(() => {
    const current = { active: true, pending: 0 };
    session.current = current;
    setUploading(0);
    return () => { current.active = false; };
  }, [scope]);
  const addFiles = async incoming => {
    const current = session.current;
    if (!current?.active) return;
    const batch = [...(incoming || [])];
    if (filesRef.current.length + current.pending + batch.length > MAX_FILES) {
      setStatus(`Up to ${MAX_FILES} attachments per task or message.`); return;
    }
    current.pending += batch.length;
    setUploading(current.pending);
    for (const file of batch) {
      if (!current.active) break;
      try {
        if (file.size > MAX_BYTES) throw Error("larger than 10 MB");
        const response = await fetch("/attachments", {
          method: "POST", headers: { "content-type": file.type || "application/octet-stream",
            "x-attachment-filename": encodeURIComponent(file.name || "attachment") }, body: file,
        });
        const body = await response.json();
        if (!response.ok || !body.name) throw Error(body.detail?.error || `upload failed (${response.status})`);
        if (current.active) {
          const next = [...new Set([...filesRef.current, body.name])];
          filesRef.current = next; setFiles(next);
        }
      } catch (error) {
        if (current.active) setStatus(`${file.name || "File"} not added: ${error.message}`);
      } finally {
        current.pending--;
        if (current.active) setUploading(current.pending);
      }
    }
  };
  return { uploading, dragging, addFiles,
    remove: name => setFiles(prev => prev.filter(x => x !== name)),
    onPaste: e => {
      const pasted = [...(e.clipboardData?.files || [])];
      if (pasted.length) { e.preventDefault(); addFiles(pasted); }
    },
    dropProps: {
      onDragOver: e => { if (hasFiles(e)) { e.preventDefault(); setDragging(true); } },
      onDragLeave: e => { if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false); },
      onDrop: e => { if (hasFiles(e)) { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); } },
    },
  };
}

export function AttachmentLink({ name }) {
  const [missing, setMissing] = useState(false);
  if (missing) return html`<span class="image-expired">Attachment unavailable</span>`;
  return html`<a class=${isImage(name) ? "image-link" : "file-link"} href=${`/attachments/${name}`} target="_blank" rel="noopener" title=${isImage(name) ? "Open image" : `Download ${attachmentLabel(name)}`}>
    ${isImage(name) ? html`<img src=${`/attachments/${name}`} alt="Attached image" loading="lazy" onError=${() => setMissing(true)} />`
      : html`<span aria-hidden="true">▤</span> ${attachmentLabel(name)} <span aria-hidden="true">↓</span>`}
  </a>`;
}

export function AttachmentList({ files = [] }) {
  return files.length > 0 && html`<div class="attachment-list">${files.map(name => html`<${AttachmentLink} key=${name} name=${name} />`)}</div>`;
}

export function AttachmentPicker({ files, controls, disabled = false }) {
  const input = useRef(null);
  return html`<div class="attachment-picker">
    <div class="attachment-tools"><button type="button" class="mini" disabled=${disabled} onClick=${() => input.current?.click()}>+ attach files</button><span>Paste or drop files · 10 MB each · up to 10</span></div>
    <input ref=${input} type="file" multiple hidden disabled=${disabled} onChange=${e => { controls.addFiles(e.target.files); e.target.value = ""; }} />
    ${(files.length > 0 || controls.uploading > 0) && html`<div class="compose-images">${files.map(name => html`<figure key=${name} class="compose-image">
      <${AttachmentLink} name=${name} /><button type="button" class="remove" disabled=${disabled} onClick=${() => controls.remove(name)} aria-label=${`Remove ${attachmentLabel(name)}`}>×</button>
    </figure>`)}${controls.uploading > 0 && html`<span role="status">Uploading ${controls.uploading}…</span>`}</div>`}
  </div>`;
}
