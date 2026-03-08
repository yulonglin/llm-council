# Fix `eval` reserved word + Add sidebar search bar

## Context

The frontend fails to build because `eval` (a restricted identifier in strict mode) is used as a `.map()` parameter in Stage2.jsx. The user also wants a search bar to filter conversations in the sidebar.

## Changes

### 1. Fix `eval` in Stage2.jsx

File: `frontend/src/components/Stage2.jsx`

Two edits — lines 139 and 145:
- `data.map((eval, index) =>` → `data.map((evaluation, index) =>`
- `{shortModel(eval.model)}` → `{shortModel(evaluation.model)}`

No other files affected. Confirmed these are the only two occurrences.

### 2. Add search bar to Sidebar.jsx

File: `frontend/src/components/Sidebar.jsx`

**a) Add React import** (currently has none):
```jsx
import { useState } from 'react';
```

**b) Add search state** at top of component:
```jsx
const [searchQuery, setSearchQuery] = useState('');
```

**c) Filter BEFORE the pinned/unpinned/archived split** (critical — filtering after would miss conversations in some sections):
```jsx
const filtered = searchQuery.trim()
  ? conversations.filter((conv) =>
      (conv.title || 'New Conversation')
        .toLowerCase()
        .includes(searchQuery.trim().toLowerCase())
    )
  : conversations;

const pinned = filtered.filter(...);
const unpinned = filtered.filter(...);
const archived = filtered.filter(...);
```

Note: `conv.title || 'New Conversation'` matches the same fallback used in `renderConversation`.

**d) Add search input** inside `.sidebar-header`, after the archive toggle button (takes advantage of existing `flex-direction: column; gap: 10px`):
```jsx
<input
  type="text"
  className="search-input"
  placeholder="Search conversations..."
  value={searchQuery}
  onChange={(e) => setSearchQuery(e.target.value)}
/>
```

**e) Distinct empty states** — "No matching conversations" (search miss) vs "No conversations yet" (truly empty).

### 3. Style search input in Sidebar.css

File: `frontend/src/components/Sidebar.css`

Matching existing conventions: `border: 1px solid #d0d0d0`, `border-radius: 6px`, `font-size: 13px`, focus border `#4a90e2`.

## Verification

- `cd frontend && npx vite build` — no more `eval` error
- Search bar visible in sidebar, filters all sections (pinned, unpinned, archived) in real-time
- Empty search shows all conversations; no-match shows "No matching conversations"
