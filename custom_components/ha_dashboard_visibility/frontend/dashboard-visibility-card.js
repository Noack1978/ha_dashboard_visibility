class DashboardVisibilityCard extends HTMLElement {
  constructor() {
    super();
    this._initialized = false;
    this._dashboards = [];
    this._users = [];
    this._matrix = {};
    this._config = {};
  }

  setConfig(config) {
    this._config = config || {};
    // Wenn die Karte schon Daten geladen hat (z. B. Änderung im visuellen
    // Editor), nur die Tabelle neu aufbauen statt alles neu zu laden.
    if (this._initialized && this._content && this._dashboards.length) {
      this._renderTable();
    }
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("dashboard-visibility-card-editor");
  }

  getCardSize() {
    const rows = this._dashboards ? this._dashboards.length : 3;
    return 1 + Math.max(rows, 1);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._render();
    }
  }

  _visibleUsers() {
    const selected = Array.isArray(this._config.users) ? this._config.users : null;
    if (!selected) return this._users; // kein Filter gesetzt = alle anzeigen
    return this._users.filter((u) => selected.includes(u.id));
  }

  async _render() {
    if (!this._hass) return;

    const root = this.attachShadow ? this.shadowRoot || this.attachShadow({ mode: "open" }) : this;
    root.innerHTML = `
      <ha-card header="Sichtbarkeit pro Benutzer (Dashboards & Panels)">
        <div class="card-content" id="content">
          <p>Lade Daten ...</p>
        </div>
      </ha-card>
      <style>
        ha-card { padding-bottom: 8px; }
        .card-content { overflow-x: auto; padding: 0 16px 16px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
        th { font-weight: 500; color: var(--secondary-text-color); white-space: nowrap; }
        td.dashboard-name { text-align: left; white-space: nowrap; color: var(--primary-text-color); vertical-align: middle; }
        td.dashboard-name ha-icon { vertical-align: middle; }
        .name-block { display: inline-flex; flex-direction: column; vertical-align: middle; }
        .path-hint { font-style: italic; font-size: 0.75em; color: var(--secondary-text-color); }
        tr.group-row td { text-align: left; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; font-size: 0.8em; color: var(--secondary-text-color); background: var(--secondary-background-color, rgba(127,127,127,0.08)); border-bottom: none; padding-top: 14px; }
        .hint { color: var(--secondary-text-color); font-size: 0.9em; margin: 0 0 8px; }
        input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; }
        .error { color: var(--error-color, red); }
      </style>
    `;
    this._content = root.getElementById("content");

    if (!this._hass.user || !this._hass.user.is_admin) {
      this._content.innerHTML = `<p class="error">Diese Karte ist nur für Administratoren sichtbar.</p>`;
      return;
    }

    try {
      await this._loadData();
      this._renderTable();
    } catch (err) {
      console.error("dashboard-visibility-card: failed to load data", err);
      this._content.innerHTML = `<p class="error">Daten konnten nicht geladen werden: ${err.message || err}</p>`;
    }
  }

  async _loadData() {
    const result = await this._hass.callWS({ type: "ha_dashboard_visibility/get_data" });
    this._dashboards = result.dashboards || [];
    this._users = result.users || [];
    this._matrix = result.matrix || {};
  }

  _renderTable() {
    if (!this._dashboards.length) {
      this._content.innerHTML = `<p>Keine Dashboards gefunden.</p>`;
      return;
    }
    const visibleUsers = this._visibleUsers();
    if (!visibleUsers.length) {
      this._content.innerHTML = `<p>Keine Benutzer ausgewählt. Im Karten-Editor mindestens einen Benutzer aktivieren.</p>`;
      return;
    }

    let html = `<p class="hint">Häkchen = Eintrag ist für diesen Benutzer in der Sidebar sichtbar. Kursiv unter dem Namen: technischer Pfad (url_path) und Panel-Typ (component_name) – zur Einordnung, was ein Eintrag eigentlich ist.</p>`;
    html += `<table><thead><tr><th style="text-align:left;">Dashboard / Panel</th>`;
    for (const user of visibleUsers) {
      html += `<th>${this._escape(user.name)}${user.is_admin ? " (Admin)" : ""}</th>`;
    }
    html += `</tr></thead><tbody>`;

    let currentGroup = null;
    for (const dash of this._dashboards) {
      const group = dash.component_name || "(ohne component_name)";
      if (group !== currentGroup) {
        currentGroup = group;
        const colspan = 1 + visibleUsers.length;
        html += `<tr class="group-row"><td colspan="${colspan}">${this._escape(group)}</td></tr>`;
      }

      html += `<tr><td class="dashboard-name">`;
      html += `${dash.icon ? `<ha-icon icon="${dash.icon}" style="margin-right:6px;"></ha-icon>` : ""}`;
      html += `<div class="name-block"><span>${this._escape(dash.title)}</span>`;
      html += `<span class="path-hint">${this._escape(dash.url_path)}</span></div></td>`;
      for (const user of visibleUsers) {
        const hidden = !!(this._matrix[user.id] && this._matrix[user.id][dash.url_path]);
        const checked = !hidden;
        html += `<td><input type="checkbox" data-user="${user.id}" data-dashboard="${dash.url_path}" ${checked ? "checked" : ""}></td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;

    this._content.innerHTML = html;

    const checkboxes = this._content.querySelectorAll("input[type=checkbox]");
    checkboxes.forEach((cb) => {
      cb.addEventListener("change", (ev) => this._onToggle(ev));
    });
  }

  async _onToggle(ev) {
    const cb = ev.target;
    const userId = cb.dataset.user;
    const urlPath = cb.dataset.dashboard;
    const hidden = !cb.checked;

    cb.disabled = true;
    try {
      await this._hass.callWS({
        type: "ha_dashboard_visibility/set_hidden",
        user_id: userId,
        url_path: urlPath,
        hidden,
      });
      if (!this._matrix[userId]) this._matrix[userId] = {};
      this._matrix[userId][urlPath] = hidden;
    } catch (err) {
      console.error("dashboard-visibility-card: failed to update", err);
      cb.checked = !cb.checked; // revert on failure
      alert("Änderung konnte nicht gespeichert werden: " + (err.message || err));
    } finally {
      cb.disabled = false;
    }
  }

  _escape(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }
}

customElements.define("dashboard-visibility-card", DashboardVisibilityCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dashboard-visibility-card",
  name: "Dashboard Visibility Card",
  description: "Steuert pro Benutzer, welche Dashboards/Panels in der Sidebar sichtbar sind.",
});

/**
 * Visueller Editor: lässt einen Admin auswählen, welche Benutzer als
 * Spalten angezeigt werden (Standard: alle). Reduziert die Breite der
 * Karte, indem man nicht benötigte Benutzer-Spalten abwählt.
 */
class DashboardVisibilityCardEditor extends HTMLElement {
  constructor() {
    super();
    this._initialized = false;
    this._config = {};
    this._users = [];
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._renderAsync();
    }
  }

  async _renderAsync() {
    const root = this.attachShadow ? this.shadowRoot || this.attachShadow({ mode: "open" }) : this;
    root.innerHTML = `
      <div id="content"><p>Lade Benutzer ...</p></div>
      <style>
        .hint { color: var(--secondary-text-color); font-size: 0.9em; margin: 0 0 8px; }
        .row { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
        input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; }
        .error { color: var(--error-color, red); }
      </style>
    `;
    this._content = root.getElementById("content");

    if (!this._hass.user || !this._hass.user.is_admin) {
      this._content.innerHTML = `<p class="error">Nur für Administratoren editierbar.</p>`;
      return;
    }

    try {
      const result = await this._hass.callWS({ type: "ha_dashboard_visibility/get_data" });
      this._users = result.users || [];
      this._renderCheckboxes();
    } catch (err) {
      console.error("dashboard-visibility-card-editor: failed to load users", err);
      this._content.innerHTML = `<p class="error">Benutzer konnten nicht geladen werden.</p>`;
    }
  }

  _renderCheckboxes() {
    if (!this._users.length) {
      this._content.innerHTML = `<p>Keine Benutzer gefunden.</p>`;
      return;
    }
    const selected = Array.isArray(this._config.users) ? this._config.users : null;

    let html = `<p class="hint">Welche Benutzer sollen als Spalten in der Karte angezeigt werden? Standard: alle. Abwählen reduziert die Kartenbreite.</p>`;
    for (const user of this._users) {
      const checked = selected ? selected.includes(user.id) : true;
      html += `<label class="row"><input type="checkbox" data-user="${user.id}" ${checked ? "checked" : ""}><span>${this._escape(user.name)}${user.is_admin ? " (Admin)" : ""}</span></label>`;
    }
    this._content.innerHTML = html;

    this._content.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.addEventListener("change", () => this._onChange());
    });
  }

  _onChange() {
    const checkboxes = Array.from(this._content.querySelectorAll("input[type=checkbox]"));
    const selected = checkboxes.filter((cb) => cb.checked).map((cb) => cb.dataset.user);

    const newConfig = { ...this._config };
    if (selected.length === checkboxes.length) {
      // alle ausgewählt = kein Filter, sauberer Default statt langer Liste
      delete newConfig.users;
    } else {
      newConfig.users = selected;
    }
    this._config = newConfig;

    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config: newConfig }, bubbles: true, composed: true })
    );
  }

  _escape(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }
}

customElements.define("dashboard-visibility-card-editor", DashboardVisibilityCardEditor);
