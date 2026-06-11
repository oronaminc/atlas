---
name: frontend-check
description: Run typecheck+build+lint after frontend changes. Always use after modifying files under frontend/.
---

# Frontend verification

```bash
cd frontend
pnpm build    # tsc -b + vite build — must pass with 0 type errors
pnpm lint     # 0 errors (1 pre-existing actionTypes warning in use-toast.ts is OK)
```

## Gotchas

- New screens reuse existing patterns: `PageHeader` + `DataTable` (cursor pagination) + dialog forms (zod + react-hook-form + FormField).
- API calls go through hooks in `src/api/queries.ts` (use the `useList`/`useApiMutation` helpers); never call fetch directly.
- Colors/spacing via Tailwind tokens only. Register new routes in `App.tsx` + sidebar navItems in `app-layout.tsx`.
- Add strings to `src/locales/{ko,en}.json` (ko is the default; UI strings stay Korean).
- Any component using Monaco must `import "@/lib/monaco"` (local bundle; CDNs are blocked).
- Auth 401 handling: `/auth/login` and `/auth/refresh` are excluded from the auto-refresh logic in client.ts — keep it that way.
