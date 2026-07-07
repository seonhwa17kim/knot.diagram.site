## 2026.0707(月)17:13 [git: 497b33a6]

- `knot.diagram.site` 저장소에 GitHub Actions 자동배포 설정 추가.
- 새 파일 `.github/workflows/pages-deployment.yaml` 생성.
  - `main` branch push 및 `workflow_dispatch` 시 Cloudflare Pages `knot-diagram-site` 프로젝트로 배포하도록 구성.
  - `cloudflare/wrangler-action@v3` 사용.
  - Pages 업로드 직전 `.github/` 디렉토리를 이동시켜 workflow 파일이 정적 자산으로 노출되지 않도록 처리.
- GitHub repository secret `CLOUDFLARE_ACCOUNT_ID` 등록 완료.
- 남은 수동 단계: Cloudflare API Token 생성 후 GitHub repository secret `CLOUDFLARE_API_TOKEN` 등록.
- 확인 메모:
  - 현재 로컬 Wrangler OAuth access token은 `2026-07-08` 만료 예정이라 GitHub Actions용 장기 credential로는 부적합.
  - 현재 저장소에는 `_worker.js`, `_routes.json`, `robots.txt`가 없으며, 이전 Functions 과금 이슈를 재도입하는 변경은 이번 작업에 포함하지 않음.

## 2026.0707(月)19:47 [git: 284d98f8]

- GitHub Actions 재실행 결과, `CLOUDFLARE_API_TOKEN` 누락 문제 해소 후에도 Pages 업로드가 실패함을 확인.
- 실패 원인:
  - Cloudflare Pages 개별 파일 크기 제한 `25 MiB` 초과
  - 문제 파일: `reports/parabolic_volume_validation/knotinfo_volume_comparison.csv` (`36.8 MiB`)
- 코드/정적 자산 검색 결과, `reports/` 디렉토리는 사이트 런타임이 아니라 검증 스크립트 산출물 보관용임을 확인.
- `.github/workflows/pages-deployment.yaml` 수정:
  - 직접 repo 루트를 업로드하지 않고, 임시 `pages-deploy` 디렉토리를 만들어 `rsync`로 복사 후 업로드
  - 제외 대상: `.git`, `.github`, `reports`
- 로컬 검증:
  - `/tmp/knot-pages-deploy-check` 생성 후 동일한 exclude 규칙 적용
  - `25 MiB` 초과 파일 없음 확인
