---
name: frontend-check
description: frontend 코드 수정 후 타입체크+빌드+린트 검증. frontend/ 아래 파일을 수정했을 때 항상 사용.
---

# Frontend 검증

```bash
cd frontend
pnpm build    # tsc -b + vite build — 타입에러 0이어야 함
pnpm lint     # 에러 0 (use-toast.ts의 actionTypes 경고 1개는 기존 것, 무시)
```

## 주의

- 새 화면은 기존 패턴 재사용: `PageHeader` + `DataTable`(cursor 페이지네이션) + 다이얼로그 폼(zod+react-hook-form+FormField).
- API 호출은 `src/api/queries.ts`에 hook 추가 (`useList`/`useApiMutation` 헬퍼 사용), fetch 직접 호출 금지.
- 색상/간격은 Tailwind 토큰만. 신규 라우트는 `App.tsx` + 사이드바 `app-layout.tsx` navItems에 등록.
- 문자열은 `src/locales/{ko,en}.json`에 추가 (ko 기본).
- Monaco 사용하는 컴포넌트는 반드시 `import "@/lib/monaco"` (CDN 차단 환경 대응).
- auth 401 처리: `/auth/login`·`/auth/refresh`는 client.ts의 자동 refresh 로직에서 제외되어 있음 — 유지할 것.
