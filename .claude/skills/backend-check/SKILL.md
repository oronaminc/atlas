---
name: backend-check
description: backend 코드 수정 후 테스트+린트+마이그레이션 검증. backend/ 아래 파일을 수정했을 때 항상 사용.
---

# Backend 검증

backend/ 수정 후 순서대로 실행. 전부 통과해야 커밋.

```bash
cd backend
uv run pytest -q                  # 44+ tests, 실패 0이어야 함
uv run ruff check . && uv run black --check .
```

모델/마이그레이션을 건드렸다면 추가로:

```bash
rm -f /tmp/_mig.db && DATABASE_URL="sqlite+aiosqlite:////tmp/_mig.db" uv run alembic upgrade head && rm -f /tmp/_mig.db
```

## 주의

- 새 마이그레이션은 명시적 alembic op로 작성 (0001처럼 metadata.create_all 쓰지 말 것).
- 테스트는 SQLite로 돈다 — JSONB 등 PG 전용 타입은 `app/models/base.py::JsonType` 패턴(variant) 사용.
- async 세션에서 lazy load(MissingGreenlet) 주의: 관계 접근이 필요하면 selectinload로 명시 로드.
  (전례: rule_groups 라우터 `load_group()` 참고)
- 외부 API 호출 추가 시 `integrations/base.py` 경유 — X-Scope-OrgID 중복 주입 금지.
- 새 쓰기 엔드포인트는 record_audit + (룰 관련이면) mark_ruler_pending 필수.
