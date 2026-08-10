class DashboardVisibilityCard extends HTMLElement {
  constructor() {
    super();
    this._initialized = false;
    this._dashboards = [];
    this._users = [];
    this._matrix = {};
  }

  setConfig(config) {
    this._config = config || {};
  }

  static getStubConfig() {
    return {};
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
    if (!this._users.length) {
      this._content.innerHTML = `<p>Keine Benutzer gefunden.</p>`;
      return;
    }

    let html = `<p class="hint">Häkchen = Eintrag ist für diesen Benutzer in der Sidebar sichtbar. Kursiv unter dem Namen: technischer Pfad (url_path) und Panel-Typ (component_name) – zur Einordnung, was ein Eintrag eigentlich ist.</p>`;
    html += `<table><thead><tr><th style="text-align:left;">Dashboard / Panel</th>`;
    for (const user of this._users) {
      html += `<th>${this._escape(user.name)}${user.is_admin ? " (Admin)" : ""}</th>`;
    }
    html += `</tr></thead><tbody>`;

    let currentGroup = null;
    for (const dash of this._dashboards) {
      const group = dash.component_name || "(ohne component_name)";
      if (group !== currentGroup) {
        currentGroup = group;
        const colspan = 1 + this._users.length;
        html += `<tr class="group-row"><td colspan="${colspan}">${this._escape(group)}</td></tr>`;
      }

      html += `<tr><td class="dashboard-name">`;
      html += `${dash.icon ? `<ha-icon icon="${dash.icon}" style="margin-right:6px;"></ha-icon>` : ""}`;
      html += `<div class="name-block"><span>${this._escape(dash.title)}</span>`;
      html += `<span class="path-hint">${this._escape(dash.url_path)}</span></div></td>`;
      for (const user of this._users) {
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
  description: "Steuert pro Benutzer, welche Dashboards in der Sidebar sichtbar sind.",
});
