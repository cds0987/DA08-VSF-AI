# Frontend Token/Auth Analysis

Ngay hien tai frontend co rui ro chinh o viec refresh token khong nhat quan giua cac duong goi API. Cac request di qua `axiosClient` co interceptor refresh token, nhung mot so luong quan trong dung `fetchEventSource` hoac `$fetch` truc tiep nen bo qua interceptor nay. Ket qua la website co the loi sau khi access token het han, du refresh token van con hop le.

## Pham vi kiem tra

- Chat app: `src/frontend/chat`
- Admin app: `src/frontend/admin`
- Shared/base layer: `src/frontend/base`
- Backend auth lien quan:
  - User Service: `src/user-service/app/interfaces/api/routers/auth.py`
  - Query Service: `src/query-service/app/infrastructure/auth/auth_service.py`
  - Query API dependencies: `src/query-service/app/interfaces/api/dependencies.py`

## Ket luan ngan

Van de lon nhat khong phai login sai endpoint, ma la frontend dang co nhieu co che goi API khac nhau:

- `axiosClient`: co gan Bearer token va co refresh token khi gap `401`.
- `fetchEventSource`: tu gan Bearer token, khong tu refresh token.
- `$fetch`: mot so ham co boc refresh, mot so ham khong.

Dieu nay tao ra trang thai "dang nhap nhin nhu con hop le tren UI" nhung request phia sau lai bi `401`.

## Hien trang token/cookie

### Chat app

File: `src/frontend/chat/app/lib/cookie.ts`

- Access token cookie: `eka.chat.access_token`
- Session user cookie: `eka.chat.session.user`

### Admin app

File: `src/frontend/admin/app/lib/cookie.ts`

- Access token cookie: `eka.admin.access_token`
- Session user cookie: `eka.admin.session.user`

### Base layer

File: `src/frontend/base/app/lib/cookie.ts`

- Access token cookie: `access_token` (khong co prefix `eka`)
- Session user cookie: `eka.session.user`

Base layer dung ten cookie khac han chat (`eka.chat.*`) va admin (`eka.admin.*`). Trong cau hinh hien tai, chat/admin khong thay `extends '../base'`; hai app dang co code rieng copy tu base va da phan ky o nhieu diem quan trong (xem Van de 7).

### Backend refresh token

File: `src/user-service/app/interfaces/api/routers/auth.py`

- Refresh token cookie: `refresh_token`
- Cookie path: `/`
- HttpOnly: true
- SameSite: lax
- Secure: `settings.cookie_secure` (default `false`, configurable qua env var)

Access/session cookie cua chat va admin da tach rieng, nhung refresh token cookie van dung chung ten `refresh_token`. Neu chat/admin chay cung host/domain va cung path cookie, khi cung mot browser dang nhap ca chat va admin, refresh token co the bi ghi de giua hai app. Neu deploy khac subdomain voi cookie host-only, muc do rui ro se khac va can kiem tra lai bang deployment thuc te.

## Luong dang nhap

### Chat login

File: `src/frontend/chat/app/lib/api/authService.ts`

- Goi `POST /auth/login`
- Luu access token vao `eka.chat.access_token`
- Sau do trang login goi `/auth/me` de lay profile va luu session user.

File: `src/frontend/chat/app/pages/login.vue`

- Sau login thanh cong, redirect ve `/chat`.
- Neu login fail voi `401`, hien toast sai email/mat khau.
- Neu `423`, hien toast account locked.

### Admin login

File: `src/frontend/admin/app/lib/api/authService.ts`

- Goi `POST /auth/admin/login`
- Luu access token vao `eka.admin.access_token`
- Co check role admin sau khi lay `/auth/me`.

Ket luan: admin khong dang bi loi do dung nham endpoint login user thuong. Admin da dung endpoint rieng `/auth/admin/login`.

## Axios interceptor

File:

- `src/frontend/chat/app/lib/api/axiosClient.ts`
- `src/frontend/admin/app/lib/api/axiosClient.ts`

Interceptor hien tai lam dung cac viec quan trong:

- Gan base URL/runtime config.
- Gan path prefix theo service (`user`, `document`, `query`, `hr`, `mcp`).
- Gan `X-Request-ID` header (random UUID).
- Gan `Authorization-Gateway` neu co.
- Gan Bearer token tu cookie access token rieng cua tung app.
- Bo qua gan token cho cac URL chua `/auth/login`, `/auth/refresh`, `/auth/token`.
- Khi response `401`, goi `/auth/refresh`.
- Neu refresh thanh cong, luu access token moi va retry request cu.
- Neu refresh that bai, xoa access/session cookie va redirect ve login.

Dac biet, ca chat va admin deu co **dedup logic** cho refresh: mot `refreshPromise` singleton dam bao nhieu request gap `401` dong thoi chi trigger **mot lan** goi `/auth/refresh`. Dieu nay tranh tinh huong nhieu request cung luc tao ra nhieu refresh call chong cheo.

Day la luong on nhat trong frontend hien tai.

## Van de 1: Chat SSE khong refresh token

File: `src/frontend/chat/app/stores/chat.ts`

Chat gui cau hoi bang:

```ts
fetchEventSource(`${queryService.baseUrl}/query`, ...)
```

Header token lay tu:

```ts
getQueryServiceAuthHeaders()
```

Nhung request nay khong di qua `axiosClient`, nen khong duoc interceptor refresh token xu ly.

Backend `/query` yeu cau Bearer token:

- `src/query-service/app/interfaces/api/routers/query.py`
- `src/query-service/app/interfaces/api/dependencies.py`

Query service ho tro 3 auth mode (cau hinh qua `settings.auth_mode`):

- `mock`: dung mock token co dinh cho dev/test.
- `jwt`: decode JWT local bang `jwt_secret_key`.
- `user_service`: forward Bearer token sang User Service `GET /auth/me` de verify.

Trong mode `user_service`, moi request `/query` hoac `/notifications` deu tao 1 HTTP call noi bo sang User Service. Neu User Service cham hoac down, query service cung bi anh huong.

User Service mac dinh access token TTL la 15 phut:

- `src/user-service/app/core/config.py`
- `ACCESS_TOKEN_TTL_MINUTES`, default `15`

Tac dong:

- User de tab mo lau hon access token TTL.
- Sau do gui cau hoi moi.
- `/query` tra `401`.
- UI co the bao session expired hoac hien loi chat, trong khi refresh token van co the con hop le.

Ghi chu khi fix: store da co san flag `hasStartedStreaming` va `completed` trong `chat.ts` (vung quanh `onmessage`/`onclose`). Day la co so ky thuat de implement retry an toan: chi can refresh + retry mot lan khi `401` xay ra trong `onopen` (truoc khi co token dau tien), va tuyet doi khong retry sau khi `hasStartedStreaming === true` de tranh duplicate cau tra loi.

## Van de 2: Notification SSE co the chet sau khi token het han

File: `src/frontend/chat/app/stores/notifications.ts`

Notification stream dung:

```ts
fetchEventSource(`${queryService.baseUrl}/notifications`, ...)
```

Khi gap `401`, code hien tai:

```ts
started = false
stopped = true
```

Khong co buoc refresh token va reconnect.

Tac dong:

- Notification realtime co the dung hoat dong sau khi access token het han.
- User van thay minh dang o trong app, nhung notification khong con cap nhat.
- Loi nay de bi bo qua vi no khong nhat thiet lam crash UI.

## Van de 3: `$fetch` refresh wrapper chua dong nhat va chua bat het dang loi

File: `src/frontend/chat/app/lib/api/queryService.ts`

Da co helper `withTokenRefresh()` cho nhieu ham:

- `fetchHistory`
- `fetchUnreadCount`
- `markNotificationRead`
- `submitFeedback`
- `fetchConversations`
- `clearConversations`
- `renameConversation`

Nhung hien tai van co ham goi `$fetch` truc tiep khong boc refresh:

- `fetchConversation`
- `deleteConversation`

Ngoai ra, helper hien tai chi check:

```ts
(e as { status?: number })?.status === 401
```

Trong khi loi tu `$fetch`/ofetch thuong co the nam o `statusCode`, `status`, hoac `response.status` tuy ngu canh. Vi vay, ngay ca cac ham da boc `withTokenRefresh()` van co rui ro khong refresh neu loi 401 duoc expose qua field khac.

Luu y muc do: lac loi 401 o day den tu hai nguon. Mot la `getQueryServiceAuthHeaders()` tu nem `QueryServiceError` (co field `.status`, nen check hien tai bat duoc). Hai la `$fetch`/ofetch khi server tra `401` se nem `FetchError`; cac ban ofetch moi expose ca `.status` lan `.statusCode`, nen `.status === 401` co the van bat duoc tuy version. Vi vay rui ro o day la "fragility phu thuoc version ofetch" chu chua chac fail trong moi truong hop. Du sao helper `getErrorStatus()` o phan P0 van la fix dung de het phu thuoc vao shape cua error.

`doRefresh()` trong `queryService.ts` cung chua co dedup nhu `axiosClient`. Neu nhieu `$fetch` cung luc gap `401`, chung co the goi `/auth/refresh` song song. Backend refresh token co rotate/revoke token cu, nen nhieu refresh call dong thoi co the tao race condition va lam mot so request fail oan.

Tac dong:

- Mo mot conversation cu hoac xoa conversation co the loi `401` neu access token het han.
- Mot so API da boc refresh nhung van co the khong refresh neu error shape khac `status`.
- Nhieu request het token cung luc co the tao nhieu refresh call chong cheo.
- Cung mot service file nhung hanh vi token khong dong nhat, gay kho debug.

## Van de 4: HR leave APIs dung `$fetch` truc tiep va khong refresh

File: `src/frontend/chat/app/lib/api/hrService.ts`

Tat ca API nghi phep/duyet phep dung `$fetch` truc tiep:

- `createLeaveRequest`
- `cancelLeaveRequest`
- `fetchPendingApprovals`
- `approveLeaveRequest`
- `rejectLeaveRequest`

Cac ham nay chi gan Bearer token hien tai tu `eka.chat.access_token`, khong co retry refresh khi gap `401`.

Tac dong:

- Cac thao tac nghi phep co the loi sau khi access token het han.
- Loi co the xuat hien khong dong nhat voi cac API chat khac vi mot so API co refresh, mot so API khong.

## Van de 5: Chat middleware chi tin session cookie

File: `src/frontend/chat/app/middleware/auth.global.ts`

Chat middleware chi check:

```ts
if (!session.user) {
  return navigateTo('/login')
}
```

No khong goi `/auth/me` de verify token khi vao app.

Nguoc lai, admin middleware co buoc fetch server profile khi chua initialized:

File: `src/frontend/admin/app/middleware/auth.global.ts`

```ts
if (!session.isInitialized && import.meta.client && to.path !== '/login') {
  await session.fetchMe()
}
```

Ngoai ra, admin middleware con enforce role:

- Neu user da dang nhap nhung khong phai admin, middleware goi `session.signOut()` va redirect ve `/login?error=forbidden`.
- Neu admin da dang nhap va truy cap `/login`, middleware redirect ve `/`.

Tac dong:

- Chat co the con `eka.chat.session.user` nhung mat hoac het han `eka.chat.access_token`.
- UI van cho vao app.
- Request API phia sau moi bao `401`.
- User cam giac website loi bat ngo, thay vi duoc redirect/login lai som hon.

## Van de 6: Refresh token cookie dung chung giua chat va admin

Backend dat refresh cookie ten chung:

```py
_REFRESH_COOKIE = "refresh_token"
path="/"
```

Trong khi frontend tach access token theo app:

- `eka.chat.access_token`
- `eka.admin.access_token`

Rui ro khi chat/admin chay cung host/domain va cookie scope giao nhau:

- Dang nhap chat voi user A.
- Dang nhap admin voi admin B tren cung browser.
- Cookie `refresh_token` bi ghi de.
- Khi chat refresh, co the nhan access token theo refresh token moi nhat, khong phai session chat ban dau.

Muc do anh huong phu thuoc cach deploy production:

- Cung host/path: rui ro cao hon vi cookie `refresh_token` duoc share.
- Khac subdomain va cookie host-only: rui ro ghi de thap hon, nhung can xac minh Set-Cookie/Domain thuc te.

Day la mot diem can duoc quyet dinh ro: refresh token nen dung chung SSO that su, hay tach theo app.

## Van de 7: Base layer phan ky lon voi chat/admin

File:

- `src/frontend/base/app/lib/cookie.ts`
- `src/frontend/base/app/lib/api/axiosClient.ts`

Base layer co nhieu khac biet quan trong so voi chat/admin:

- Cookie ten khac: `access_token` (base) vs `eka.chat.access_token` (chat) vs `eka.admin.access_token` (admin).
- axiosClient cua base **khong co refresh token logic**: khi gap `401`, no xoa cookie va redirect ve `/login` ngay, khong thu goi `/auth/refresh`.
- Base dung `import.meta.env.VITE_*` / `process.env.NUXT_PUBLIC_*` truc tiep, trong khi chat/admin dung `useRuntimeConfig()` (Nuxt 4 style).
- Base request interceptor luon gan token, khong co logic skip cho `/auth/login`, `/auth/refresh`.
- Base middleware routing co logic chuyen huong cross-app (admin user -> admin app URL, non-admin -> `/chat`).

Trong cau hinh hien tai, chat/admin khong extend base qua Nuxt `extends`. Chung la cac app doc lap co code copy tuong tu nhung da phan ky.

Tac dong:

- Developer de import nham module tu base thay vi app-specific, dan den doc/ghi sai cookie hoac mat refresh logic.
- Khi debug auth, can xac dinh dung app dang chay de tim dung file, vi moi app co hanh vi khac.
- Fix loi auth o mot app khong tu dong fix cho app khac.

## Van de 8: Refresh token cookie `secure` flag trong production

File: `src/user-service/app/core/config.py`

Backend dat refresh cookie voi:

```py
secure=settings.cookie_secure  # default: false
```

`cookie_secure` la configurable qua env var, default la `false`.

Tac dong:

- Neu production chay HTTPS nhung khong set `COOKIE_SECURE=true`, refresh token cookie se duoc gui ca qua HTTP, tao rui ro bi chup cookie qua man-in-the-middle.
- Day la diem can kiem tra deployment config, khong phai loi code.

## Van de 9: `doRefresh()` that bai khong clear session / redirect

File: `src/frontend/chat/app/lib/api/queryService.ts`

`withTokenRefresh()` khi gap `401` se goi `doRefresh()` roi retry `fn()` mot lan. Nhung neu chinh `doRefresh()` that bai (refresh token het han/invalid), no nem thang loi axios ra ngoai, KHONG xoa access/session cookie va KHONG redirect ve login.

Khac biet voi `axiosClient`:

- `axiosClient` khi refresh fail se `removeClientCookie(...)` + redirect login (co toast).
- `queryService.doRefresh()` khong co buoc nay.

Tac dong:

- Khi refresh token het han that su, cac flow di qua `$fetch` (queryService, va tuong tu hrService neu sau nay them refresh) lam user ket o trang thai loi, khong duoc dua ve login nhu flow axios.
- Hanh vi logout giua cac duong request van khong dong nhat, ngay ca sau khi them refresh.

Khi gom ve helper chung o P0, nhanh "refresh that bai" cung phai thong nhat: chi clear session/redirect khi refresh that su fail, giong axios.

## Trieu chung co the thay tren website

- Sau khi de tab mo lau, gui chat bi bao session expired hoac loi `401`.
- Notification realtime khong cap nhat nua nhung UI van dang nhap.
- Mo conversation cu loi sau mot thoi gian idle.
- Xoa conversation loi sau mot thoi gian idle.
- Tao/duyet/huy leave request loi bat ngo voi `401`.
- Admin co the on hon chat vi middleware admin verify `/auth/me` khi vao app.
- Cung la loi token nhung moi man hinh bieu hien khac nhau do moi module dung mot kieu request khac nhau.

## Uu tien xu ly de xuat

### P0 - Chuan hoa refresh cho request khong qua axios

Can co mot helper refresh token dung chung cho chat app, de:

- `fetchEventSource` cua `/query` retry mot lan neu `401` xay ra truoc khi stream bat dau.
- `fetchEventSource` cua `/notifications` refresh va reconnect neu `401`.
- Tat ca `$fetch` trong `queryService.ts` dung chung wrapper refresh.
- Tat ca `$fetch` trong `hrService.ts` dung chung wrapper refresh.

Helper nay nen co:

- `getErrorStatus(error)` doc duoc `status`, `statusCode`, va `response.status`.
- `refreshPromise` singleton de dedup refresh token call, giong `axiosClient`.
- Co che clear session/redirect login chi khi refresh that bai, khong logout gia khi refresh token con hop le (xem Van de 9 — nhanh refresh-fail phai thong nhat voi axios).
- Nguyen tac voi SSE: chi retry neu `401` xay ra truoc khi stream bat dau; khong nen replay tu giua stream vi co the duplicate cau tra loi hoac trang thai conversation. Tan dung flag `hasStartedStreaming`/`completed` da co san trong `chat.ts` (xem ghi chu o Van de 1).

Thu tu lam goi y trong P0:

1. SSE `/query` (Van de 1) — anh huong truc tiep den hanh vi gui chat, lam truoc.
2. Gom `$fetch` cua `queryService.ts` + `hrService.ts` (Van de 3, 4, 9) ve cung helper.
3. SSE `/notifications` (Van de 2) — refresh + reconnect.

### P1 - Chat middleware nen verify session

Chat middleware nen co co che tuong tu admin:

- Khi vao route protected va session chua initialized, goi `session.fetchMe()`.
- Neu fail, clear session va ve login.

Dieu nay giup tranh trang thai UI con session user nhung access token da mat/invalid.

### P1 - Quyet dinh chien luoc refresh token cookie

Can quyet dinh ro:

- Neu chat/admin la hai app doc lap: refresh cookie nen tach ten hoac path.
- Neu muon SSO that su: session frontend cung nen dong bo theo user tu `/auth/me`, khong nen de access/session cookie rieng tao cam giac hai session doc lap.

### P2 - Giam duplicate auth code

Hien tai chat/admin/base co nhieu file auth tuong tu nhau nhung co khac biet quan trong (base khong co refresh, cookie ten khac, config style khac). Nen tranh de `base` tro thanh code cu gay nham lan khi debug.

Huong tot hon:

- Mot helper token/request chung theo app cookie namespace.
- Cac service API chi dung helper do.
- SSE va `$fetch` cung di qua cung mot chinh sach auth.
- Neu base khong con dung trong production, can danh dau ro hoac loai bo de tranh import nham.

### P2 - Dam bao `cookie_secure=true` trong production

Kiem tra deployment config dam bao env var `COOKIE_SECURE=true` khi chay sau HTTPS/TLS. Day la config check, khong can thay doi code.

## Khong nen sua voi gia dinh sai

Khong nen chi tang access token TTL de che loi. Tang TTL co the lam loi it xuat hien hon, nhung khong giai quyet viec frontend co nhieu duong request khong refresh token nhat quan.

Khong nen chi redirect login moi khi gap `401`. Neu refresh token con hop le, day la logout gia va lam user mat context dang lam viec.

## Tom tat

He thong token backend co day du access token va refresh token. Frontend cung da co interceptor refresh token tot cho axios. Loi nam o viec frontend khong dung mot co che request duy nhat:

- Axios request: refresh tot.
- SSE request: khong refresh.
- Mot so `$fetch`: refresh.
- Mot so `$fetch`: khong refresh.

Vi vay, cach sua dung la chuan hoa refresh token cho tat ca cac duong request, dac biet la `fetchEventSource` va `$fetch` trong chat app.
