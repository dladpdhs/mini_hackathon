# 배포 가이드 — Render에 무료로 사이트 올리기

이 문서대로 하면 SyllaSync를 누구나 접속할 수 있는 공개 주소(예:
`https://syllasync.onrender.com`)로 올릴 수 있습니다. 무료 플랜으로 충분합니다.

> 이미 배포에 필요한 파일은 다 포함돼 있습니다: `requirements.txt`(gunicorn 포함),
> `Procfile`, `render.yaml`.

## 0. 미리 로컬에서 한 번 확인 (선택)

배포 환경과 똑같이 gunicorn으로 떠보는 테스트입니다.

```bash
pip install -r requirements.txt
gunicorn src.app:app --bind 0.0.0.0:8000
# 브라우저에서 http://localhost:8000 접속해 정상 동작 확인 후 Ctrl+C
```

## 1. 코드를 GitHub에 올리기

Render는 GitHub 저장소를 연결해 자동 배포합니다.

```bash
cd team10
git init
git add .
git commit -m "SyllaSync"
# GitHub에서 빈 저장소를 하나 만든 뒤, 그 주소로:
git remote add origin https://github.com/<your-id>/<repo>.git
git branch -M main
git push -u origin main
```

(GitHub 계정이 없으면 github.com에서 가입 → "New repository"로 빈 저장소 생성)

## 2. Render에서 웹 서비스 만들기

1. https://render.com 접속 → **GitHub 계정으로 로그인**
2. 우측 상단 **New +** → **Web Service**
3. 방금 올린 저장소 선택 → **Connect**
4. 설정값 (저장소에 `render.yaml`이 있으면 대부분 자동으로 채워집니다):
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn src.app:app --bind 0.0.0.0:$PORT`
   - **Instance Type**: Free
5. **Create Web Service** 클릭

몇 분 뒤 배포가 끝나면 `https://<서비스이름>.onrender.com` 주소가 생기고,
그 주소를 누구에게나 공유할 수 있습니다.

## 3. (선택) LLM 업로드 분석 켜기

PDF 업로드를 실시간 LLM으로 분석하려면 API 키가 필요합니다.

- Render 서비스 → **Environment** 탭 → **Add Environment Variable**
- Key: `OPENAI_API_KEY` (또는 `ANTHROPIC_API_KEY`), Value: 본인 키
- 그리고 `requirements.txt`의 `openai>=1.0` 주석(`#`)을 풀고 다시 push

> ⚠️ 공개 사이트에 키를 넣으면 아무나 업로드할 때 **비용이 발생**할 수 있습니다.
> 키를 넣지 않으면 내장 6개 과목 + 규칙 기반 분석으로 문제없이 동작하므로,
> 공개 데모에서는 키 없이 두는 것을 권장합니다.

## 알아둘 점

- **무료 플랜**은 15분간 접속이 없으면 잠들고, 다음 접속 때 깨어나는 데 ~30초 걸립니다.
- 업로드해서 추가한 과목은 메모리에만 저장되므로 서버가 재시작되면 사라집니다
  (내장 데이터셋은 항상 유지). 영구 저장이 필요하면 DB 연동이 추후 과제입니다.

## 다른 방법

- **ngrok** (`ngrok http 5000`): 내 노트북에서 서버를 켠 채 임시 공개 주소를 즉시 발급.
  발표 시연용으로 가장 빠르지만 내 컴퓨터가 꺼지면 접속 불가.
- **PythonAnywhere**: GitHub 없이 파일 업로드로도 배포 가능.
