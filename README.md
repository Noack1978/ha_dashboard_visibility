# Dashboard Visibility Manager (ha-dashboard-visibility)

Custom Integration für Home Assistant. Fügt eine Lovelace-Karte hinzu, mit
der ein Admin **von seinem eigenen Gerät aus, ohne sich als anderer Nutzer
anzumelden**, für jeden Benutzer und jedes Dashboard per Checkbox steuert,
ob das Dashboard in dessen Sidebar erscheint.

## Funktionsweise

Die Karte zeigt eine Matrix: Zeilen = Dashboards, Spalten = Benutzer,
Häkchen = "sichtbar in der Sidebar". Ein Klick speichert die Änderung
**sofort** (kein Neustart nötig).

Technisch nutzt die Integration **denselben Speicherplatz**, den Home
Assistant nativ für "Reihenfolge ändern und Elemente aus der Seitenleiste
ausblenden" im Benutzerprofil verwendet (Storage-Key
`frontend.user_data_<user_id>`, Datenschlüssel `sidebar` mit
`hiddenPanels`/`panelOrder`). Die Karte ist also nur eine zweite Tür zum
gleichen Raum – sie kollidiert nicht mit der nativen Profil-Einstellung,
im Gegenteil, beide zeigen immer denselben Stand.

## Wichtiger Hinweis zur Kompatibilität

Dieser Storage-Mechanismus ist Teil der internen Frontend-Implementierung
und **nicht offiziell als stabile API dokumentiert** (im Gegensatz z. B.
zu `async_register_static_paths` oder den WebSocket-Commands). Er wird
seit Jahren unverändert für genau diesen Zweck genutzt (auch die
native Profil-Funktion "Elemente ausblenden" basiert darauf), gilt aber
nicht als offiziell garantiert. Falls ein zukünftiges HA-Frontend-Major-
Update dieses Speicherformat ändert, würde die Karte ggf. nicht mehr
greifen (sie würde dann einfach nichts mehr bewirken, nicht abstürzen).
Sollte HA künftig eine offizielle Admin-API zum Setzen der Sidebar
anderer Nutzer anbieten, ist ein Umstieg empfehlenswert.

**Wichtig:** Dies blendet Dashboards nur in der **Sidebar** aus (wie
`custom-sidebar`). Ein technisch versierter Nutzer, der die Dashboard-URL
kennt, könnte sie weiterhin direkt aufrufen. Für einen echten Zugriffs-
schutz zusätzlich die native "Sichtbar für"-Einstellung pro Dashboard
setzen (Einstellungen → Dashboards → Dashboard bearbeiten).

## Installation

1. ZIP entpacken, Ordner `ha_dashboard_visibility` nach
   `/config/custom_components/` kopieren
2. Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen →
   "Dashboard Visibility Manager" suchen und hinzufügen (keine weitere
   Konfiguration nötig)
4. Die Karte `custom:dashboard-visibility-card` ist danach in jedem
   Dashboard verfügbar (Lovelace-Ressource wird automatisch registriert)

## Verwendung

Karte zu einem beliebigen (eigenen, Admin-only) Dashboard hinzufügen:

```yaml
type: custom:dashboard-visibility-card
```

Kein weiterer Konfigurationsparameter nötig. Die Karte lädt beim Öffnen
automatisch alle Dashboards und Benutzer und zeigt die aktuelle Sichtbarkeit.

## Grenzen

- Zeigt alle Panels, die HA selbst als sidebar-fähig markiert
  (`show_in_sidebar: true`) – also eigene Dashboards, Integrations-Panels
  (z. B. Energie, Karte, Kalender, To-do) und Add-on-/Ingress-Panels
  (z. B. Terminal, File editor, HACS). Rein technische Einträge ohne
  eigenständigen Sidebar-Nutzen sind fest ausgeschlossen: `notfound`
  (404-Fallback), `profile` (immer über den Avatar erreichbar), `_my_redirect`
  (technischer Weiterleitungs-Mechanismus), `config` und `app` (Häkchen ohne
  Auswirkung auf die Sichtbarkeit, bestätigt getestet)
- Einträge werden nach `component_name` gruppiert; unter jedem Namen steht
  klein und kursiv der technische `url_path` zur Einordnung
- Sichtbarkeit wirkt sofort, aber der Benutzer sieht die Änderung erst
  nach einem Sidebar-/Seiten-Reload
- Bei manchen Add-on-/Ingress-Panels ist nicht in jedem Fall verifiziert,
  ob das Ausblenden genauso zuverlässig greift wie bei regulären
  Dashboards – im Zweifel selbst gegentesten
- Kein visueller Karten-Editor (nur YAML-Konfiguration, siehe oben) – ist
  aber wegen fehlender Optionen auch nicht nötig
