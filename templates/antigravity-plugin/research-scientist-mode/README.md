# Research Scientist Session Mode Plugin (`research-scientist-mode`)

Global Antigravity plugin providing a **per-conversation** on/off switch for the `research-scientist` methodology — similar to toggling `/goal`, without modifying unrelated chats or requiring per-project setup files.

## Commands

- **`/research-scientist ...`** (or `/research-on ...`): Activates session lock for the current conversation ID only. Re-anchors every 6 follow-up turns or immediately after context compaction, and activates `Stop` provenance checks on `project_state.json`.
- **`/research-off`**: Exposes `/research-off` in the slash menu, clears the lock for the current conversation ID, and restores normal chat behavior.

## Install

Copy this plugin directory into Antigravity's global plugins folder:

```bash
cp -r templates/antigravity-plugin/research-scientist-mode ~/.gemini/config/plugins/
chmod +x ~/.gemini/config/plugins/research-scientist-mode/hooks/session_mode_hook.py
```

Restart or open a new turn/chat in Antigravity. Manage or temporarily disable the plugin anytime under **Customizations -> Plugins -> Research Scientist Session Mode**.
