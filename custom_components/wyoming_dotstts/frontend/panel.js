/* dots.TTS — Home Assistant custom panel.
 *
 * Voice profile management (list / play / upload / delete / test synthesis)
 * rendered inside the HA frontend. All API calls go through the integration's
 * authenticated proxy (/api/wyoming_dotstts/proxy/...), so the API token
 * never reaches the browser and port 8180 only needs to be reachable from
 * the HA host.
 */

const STYLES = `
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :host {
    display: block;
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    min-height: 100%;
    padding: 16px;
  }
  .container { width: min(980px, 100%); margin: 0 auto; }
  h1 { font-size: 1.6rem; margin: 8px 0 4px; }
  .subtitle { color: var(--secondary-text-color); margin-bottom: 16px; }
  .card {
    background: var(--card-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 1px 4px rgba(0,0,0,0.2));
    padding: 16px 20px;
    margin: 16px 0;
  }
  .card h2 { font-size: 1.1rem; margin-bottom: 12px; }
  label { display: block; font-weight: 500; margin: 10px 0 4px; }
  input[type="text"], textarea, select {
    width: 100%; padding: 8px 10px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
    border: 1px solid var(--divider-color); border-radius: 8px;
    font: inherit;
  }
  textarea { min-height: 72px; resize: vertical; }
  button {
    border: 0; border-radius: 8px; padding: 8px 16px;
    background: var(--primary-color); color: var(--text-primary-color, #fff);
    font: inherit; font-weight: 500; cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.secondary { background: var(--secondary-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  button.danger { background: var(--error-color, #b3261e); }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
  .voice {
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
    padding: 10px 0; border-bottom: 1px solid var(--divider-color); flex-wrap: wrap;
  }
  .voice:last-child { border-bottom: 0; }
  .voice .meta { color: var(--secondary-text-color); font-size: 0.9rem; }
  .badge {
    font-size: 0.75rem; padding: 2px 8px; border-radius: 999px;
    background: var(--primary-color); color: var(--text-primary-color, #fff);
    margin-left: 8px; vertical-align: middle;
  }
  .invalid { color: var(--error-color, #b3261e); font-size: 0.9rem; }
  .status { font-size: 0.95rem; color: var(--secondary-text-color); }
  .status .ok { color: var(--success-color, #0f9d58); font-weight: 600; }
  .msg { margin-top: 10px; font-size: 0.95rem; }
  .msg.error { color: var(--error-color, #b3261e); }
  .msg.ok { color: var(--success-color, #0f9d58); }
  .checkbox { display: flex; gap: 8px; align-items: center; margin-top: 10px; }
  .checkbox input { width: auto; }
`;

class DotsTtsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._initialized = false;
    this._audio = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._render();
      this._refresh();
    }
  }

  async _api(path, options = {}) {
    const response = await this._hass.fetchWithAuth(`/api/wyoming_dotstts/proxy/${path}`, options);
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch (e) { /* keep */ }
      throw new Error(detail);
    }
    return response;
  }

  async _apiJson(path, options = {}) {
    return (await this._api(path, options)).json();
  }

  _el(id) { return this.shadowRoot.getElementById(id); }

  _msg(id, text, cls) {
    const el = this._el(id);
    el.textContent = text;
    el.className = `msg ${cls || ""}`;
  }

  async _refresh() {
    try {
      const [health, voices] = await Promise.all([
        this._apiJson("health"),
        this._apiJson("voices"),
      ]);
      this._voices = voices;
      const ready = health.ready ? '<span class="ok">ready</span>' : "loading model…";
      this._el("status").innerHTML =
        `Server: ${ready} · model <code>${health.model}</code> · seed ${health.seed ?? "random"} · gain ${health.gain_db} dB`;
      this._renderVoices();
    } catch (error) {
      this._el("status").textContent = `Server unreachable: ${error.message}`;
    }
  }

  _renderVoices() {
    const list = this._el("voices");
    const testVoice = this._el("test-voice");
    const { valid = [], invalid = [], default_voice: defaultVoice } = this._voices || {};
    list.innerHTML = "";
    testVoice.innerHTML = "";

    if (!valid.length) {
      list.innerHTML = '<div class="meta">No voice profiles yet — add one below.</div>';
    }
    for (const profile of valid) {
      const row = document.createElement("div");
      row.className = "voice";
      const isDefault = profile.name === defaultVoice;
      row.innerHTML = `
        <div>
          <strong>${profile.name}</strong>${isDefault ? '<span class="badge">default</span>' : ""}
          <div class="meta">${profile.duration_seconds ?? "?"} s — “${(profile.prompt_text || "").slice(0, 90)}”</div>
        </div>
        <div class="row" style="margin:0">
          <button class="secondary" data-play="${profile.name}">▶ Reference</button>
          <button class="danger" data-delete="${profile.name}">Delete</button>
        </div>`;
      list.appendChild(row);

      const option = document.createElement("option");
      option.value = profile.name;
      option.textContent = profile.name;
      testVoice.appendChild(option);
    }
    for (const profile of invalid) {
      const row = document.createElement("div");
      row.className = "voice";
      row.innerHTML = `<div><strong>${profile.name}</strong> <span class="invalid">invalid: ${profile.reason}</span></div>`;
      list.appendChild(row);
    }

    list.querySelectorAll("[data-play]").forEach((btn) =>
      btn.addEventListener("click", () => this._playReference(btn.dataset.play, btn)));
    list.querySelectorAll("[data-delete]").forEach((btn) =>
      btn.addEventListener("click", () => this._deleteVoice(btn.dataset.delete)));
  }

  async _playBlob(response) {
    const url = URL.createObjectURL(await response.blob());
    if (this._audio) this._audio.pause();
    this._audio = new Audio(url);
    this._audio.addEventListener("ended", () => URL.revokeObjectURL(url));
    await this._audio.play();
  }

  async _playReference(name, btn) {
    btn.disabled = true;
    try {
      await this._playBlob(await this._api(`voices/${encodeURIComponent(name)}/audio`));
    } catch (error) {
      this._msg("voices-msg", error.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  async _deleteVoice(name) {
    if (!confirm(`Delete voice profile “${name}”? This removes its files from the server.`)) return;
    try {
      await this._api(`voices/${encodeURIComponent(name)}`, { method: "DELETE" });
      this._msg("voices-msg", `Deleted “${name}”.`, "ok");
      await this._refresh();
    } catch (error) {
      this._msg("voices-msg", error.message, "error");
    }
  }

  async _addVoice() {
    const name = this._el("add-name").value.trim();
    const prompt = this._el("add-prompt").value.trim();
    const file = this._el("add-file").files[0];
    if (!name || !prompt || !file) {
      this._msg("add-msg", "Name, audio file and transcript are all required.", "error");
      return;
    }
    const form = new FormData();
    form.append("name", name);
    form.append("prompt", prompt);
    form.append("normalize", this._el("add-normalize").checked ? "true" : "false");
    form.append("audio", file);

    const btn = this._el("add-submit");
    btn.disabled = true;
    this._msg("add-msg", "Converting and saving…");
    try {
      const result = await this._apiJson("voices", { method: "POST", body: form });
      this._msg("add-msg", `Voice “${result.name}” added (${result.duration_seconds ?? "?"} s). It appears in Assist voice lists on the next describe.`, "ok");
      this._el("add-name").value = "";
      this._el("add-prompt").value = "";
      this._el("add-file").value = "";
      await this._refresh();
    } catch (error) {
      this._msg("add-msg", error.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  async _testSpeak() {
    const btn = this._el("test-submit");
    const text = this._el("test-text").value.trim();
    if (!text) return;
    btn.disabled = true;
    this._msg("test-msg", "Synthesizing… (first request after idle can take a while)");
    const started = Date.now();
    try {
      const response = await this._api("synthesize?format=wav", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: this._el("test-voice").value || null }),
      });
      await this._playBlob(response);
      this._msg("test-msg", `Done in ${((Date.now() - started) / 1000).toFixed(1)} s.`, "ok");
    } catch (error) {
      this._msg("test-msg", error.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="container">
        <h1>dots.TTS</h1>
        <div class="subtitle status" id="status">Connecting…</div>

        <div class="card">
          <h2>Voice profiles</h2>
          <div id="voices"></div>
          <div class="msg" id="voices-msg"></div>
        </div>

        <div class="card">
          <h2>Add a voice</h2>
          <label for="add-name">Name</label>
          <input type="text" id="add-name" placeholder="e.g. agata">
          <label for="add-file">Reference recording (10–15 s of clean speech; any audio format)</label>
          <input type="file" id="add-file" accept="audio/*,video/*">
          <label for="add-prompt">Exact transcript of the recording</label>
          <textarea id="add-prompt" placeholder="Word for word, with punctuation, in the recording's language."></textarea>
          <div class="checkbox">
            <input type="checkbox" id="add-normalize" checked>
            <label for="add-normalize" style="margin:0">Normalize loudness (recommended — the model clones the reference's volume)</label>
          </div>
          <div class="row"><button id="add-submit">Add voice</button></div>
          <div class="msg" id="add-msg"></div>
        </div>

        <div class="card">
          <h2>Test synthesis</h2>
          <label for="test-voice">Voice</label>
          <select id="test-voice"></select>
          <label for="test-text">Text</label>
          <input type="text" id="test-text" value="Cześć, to jest test nowego głosu.">
          <div class="row"><button id="test-submit">Speak</button></div>
          <div class="msg" id="test-msg"></div>
        </div>
      </div>`;
    this._el("add-submit").addEventListener("click", () => this._addVoice());
    this._el("test-submit").addEventListener("click", () => this._testSpeak());
  }
}

customElements.define("dots-tts-panel", DotsTtsPanel);
