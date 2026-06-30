> ⚠️ **DEPRECATED — KHÔNG dùng, KHÔNG import từ layer này.**
>
> Ý đồ ban đầu: `frontend/base` là Nuxt Layer dùng chung và `frontend/chat`, `frontend/admin`
> `extends '../base'`. **Thực tế hiện tại KHÔNG còn đúng:** chat và admin là hai app độc lập,
> **không** `extends '../base'` (kiểm tra `nuxt.config.ts` của hai app), không deploy base
> (vắng trong `docker-compose*.yml` và `nginx/nginx.conf`), và không file nào import từ đây.
>
> Layer này đã **phân kỳ** với chat/admin ở nhiều điểm nguy hiểm nếu lỡ import nhầm:
> - axiosClient của base **KHÔNG có refresh-token** (gặp 401 là xóa cookie + về login ngay).
> - Tên cookie khác: `access_token` (base) vs `eka.chat.access_token` / `eka.admin.access_token`.
> - Dùng `import.meta.env.VITE_*` thay vì `useRuntimeConfig()` như chat/admin.
>
> Chính sách auth/refresh hiện tại sống ở từng app: `frontend/chat/app/lib/api/authRefresh.ts`
> và `frontend/admin/app/lib/api/authRefresh.ts`. Khi cần sửa auth, sửa ở app tương ứng.
>
> Giữ lại tạm như tài liệu tham khảo; có thể xóa hẳn khi đã chắc không còn nhu cầu.

---

# frontend/base — Nuxt Layer dùng chung (auth qua User Service `/auth`, design system, useApi, layout) — KHÔNG deploy riêng
