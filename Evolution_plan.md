# File System & Collaboration Evolution Plan

## Overview

Extension of Synth project to support file management, multi-user sessions, and local/server execution environments.

## Architecture Summary

### Storage

```
pv-common/           # Common PVC (RWO/RWX)
├── public/          # Read-only for users, write for admins
└── shared/          # Shared files between users

pv-users/            # Per-user PVC (StatefulSet + volumeClaimTemplate)
└── {user_id}/
    ├── files/       # User's personal files
    ├── cache/       # RAG indexes, embeddings
    └── projects/    # Server-side projects
```

### Execution Modes

| Mode | Files | Tools | Scope |
|------|-------|-------|-------|
| Local UI | Local PC | Local | User's machine |
| Server UI | Server PV | Server + Local | Backend pod |

**Key principle:** Files and execution context are bound to the session mode (local or server). Chat is always shared in a session.

### Sessions

- **Shared chat:** All users in a session see messages in real-time (SSE)
- **Shared view:** Users observe chat, can take control and work with their own files
- **Lock mechanism:** Write access controlled by session owner
- **Transfer:** Owner can transfer write access to another user

### Projects

- Always server-side
- Can contain: files, RAG indexes, git repo, config, invariants
- Users can create, select existing, or delete projects
- Project selector at session creation

### Tool Routing

Tools have execution location hints. Routing determined by:
- `source: "local" | "server"` in session context
- Or tool definition with `execution: "local" | "server" | "both"`
- Or path prefix: `local://...` vs `/pv-users/...`

### Real-time Collaboration

- Session updates via SSE
- Lock for write access to session
- Owner can delegate write access

## Component Plan

### Phase 1: File Storage API
- `POST /api/files` - Upload file
- `GET /api/files/{file_id}` - Download file
- `DELETE /api/files/{file_id}` - Delete file
- `GET /api/files` - List user's files
- `PUT /api/files/{file_id}` - Update (rename, move)

### Phase 2: Shared Files
- `POST /api/files/{file_id}/share` - Share to another user
- `GET /api/files/shared` - List files shared with user
- `GET /api/common/public` - List public files (read-only)

### Phase 3: Project API
- `POST /api/projects` - Create project
- `GET /api/projects` - List user's projects
- `GET /api/projects/{id}` - Get project details
- `DELETE /api/projects/{id}` - Delete project

### Phase 4: UI File Browser
- Sidebar with two sections: "Local files" and "Server files"
- Text editor (Monaco/CodeMirror)
- Project selector

### Phase 5: Tool Execution Routing
- Distinguish local vs server tool execution
- Route based on session mode or tool definition

### Phase 6: Realtime Sessions
- SSE for session updates
- Lock/release mechanism
- Owner can transfer write access

## Technical Decisions

1. **Fileservice:** Part of backend (not separate service)
2. **Storage:** File-based on PV (no database)
3. **Per-user PVC:** StatefulSet with volumeClaimTemplate
4. **Real-time:** SSE for session updates
5. **Project structure:** Always server-side, local files accessed via client-side tools

## Open Questions

- File locking mechanism (for concurrent edits)
- Large file handling (>100MB)
- Public folder quotas
